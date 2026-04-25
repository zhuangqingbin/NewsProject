from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from news_pipeline.archive.feishu_table import FeishuBitableClient
from news_pipeline.archive.writer import ArchiveWriter
from news_pipeline.classifier.importance import ImportanceClassifier
from news_pipeline.classifier.llm_judge import LLMJudge
from news_pipeline.classifier.rules import RuleEngine
from news_pipeline.config.loader import ConfigLoader
from news_pipeline.config.schema import ClassifierRulesCfg
from news_pipeline.dedup.dedup import Dedup
from news_pipeline.llm.clients.anthropic import AnthropicClient
from news_pipeline.llm.clients.dashscope import DashScopeClient
from news_pipeline.llm.cost_tracker import CostTracker, ModelPricing
from news_pipeline.llm.extractors import (
    Tier0Classifier,
    Tier1Summarizer,
    Tier2DeepExtractor,
)
from news_pipeline.llm.pipeline import LLMPipeline
from news_pipeline.llm.prompts.loader import PromptLoader
from news_pipeline.llm.router import LLMRouter
from news_pipeline.observability.alert import BarkAlerter
from news_pipeline.observability.log import configure_logging, get_logger
from news_pipeline.pushers.common.burst import BurstSuppressor
from news_pipeline.pushers.common.message_builder import MessageBuilder
from news_pipeline.pushers.dispatcher import PusherDispatcher
from news_pipeline.pushers.factory import build_pushers
from news_pipeline.router.routes import DispatchRouter
from news_pipeline.scheduler.jobs import (
    process_pending,
    scrape_one_source,
    send_digest,
)
from news_pipeline.scheduler.runner import SchedulerRunner
from news_pipeline.scrapers.factory import build_registry
from news_pipeline.storage.dao.audit_log import AuditLogDAO
from news_pipeline.storage.dao.chart_cache import ChartCacheDAO
from news_pipeline.storage.dao.dead_letter import DeadLetterDAO
from news_pipeline.storage.dao.digest_buffer import DigestBufferDAO
from news_pipeline.storage.dao.metrics import MetricsDAO
from news_pipeline.storage.dao.news_processed import NewsProcessedDAO
from news_pipeline.storage.dao.push_log import PushLogDAO
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.dao.source_state import SourceStateDAO
from news_pipeline.storage.db import Database

PRICING = {
    "deepseek-v3": ModelPricing(input_per_m_cny=0.5, output_per_m_cny=1.5),
    "claude-haiku-4-5-20251001": ModelPricing(input_per_m_cny=7.0,
                                               output_per_m_cny=35.0),
    "claude-sonnet-4-6": ModelPricing(input_per_m_cny=21.0, output_per_m_cny=105.0),
}

log = get_logger(__name__)


async def _amain() -> None:
    cfg_dir = Path(os.environ.get("NEWS_PIPELINE_CONFIG_DIR", "config"))
    db_path = os.environ.get("NEWS_PIPELINE_DB", "data/news.db")
    once = bool(int(os.environ.get("NEWS_PIPELINE_ONCE", "0")))

    configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"), json_output=True)

    loader = ConfigLoader(cfg_dir)
    snap = loader.load()

    db = Database(f"sqlite+aiosqlite:///{db_path}")
    await db.initialize()

    raw_dao = RawNewsDAO(db)
    proc_dao = NewsProcessedDAO(db)
    state_dao = SourceStateDAO(db)
    push_log = PushLogDAO(db)
    digest_dao = DigestBufferDAO(db)
    _dlq = DeadLetterDAO(db)
    _audit = AuditLogDAO(db)
    metrics = MetricsDAO(db)
    _chart_cache = ChartCacheDAO(db)

    # LLM clients
    ds = DashScopeClient(api_key=snap.secrets.llm.get("dashscope_api_key", ""))
    cl = AnthropicClient(api_key=snap.secrets.llm.get("anthropic_api_key", ""))

    prompts = PromptLoader(cfg_dir / "prompts")
    p_versions = snap.app.llm.prompt_versions
    tier0 = Tier0Classifier(client=ds,
                            prompt=prompts.load("tier0_classify",
                                                 p_versions["tier0_classify"]))
    tier1 = Tier1Summarizer(client=ds,
                             prompt=prompts.load("tier1_summarize",
                                                  p_versions["tier1_summarize"]))
    tier2 = Tier2DeepExtractor(client=cl,
                                prompt=prompts.load("tier2_extract",
                                                     p_versions["tier2_extract"]))
    cost = CostTracker(daily_ceiling_cny=snap.app.runtime.daily_cost_ceiling_cny,
                        pricing=PRICING)
    llm_router = LLMRouter(first_party_sources={"sec_edgar", "juchao", "caixin_telegram"})
    llm = LLMPipeline(
        tier0, tier1, tier2, llm_router, cost,
        watchlist_us=[w.ticker for w in snap.watchlist.us],
        watchlist_cn=[w.ticker for w in snap.watchlist.cn],
    )

    if snap.app.classifier.rules:
        rules = RuleEngine(snap.app.classifier.rules)
    else:
        rules = RuleEngine(ClassifierRulesCfg(
            price_move_critical_pct=5.0,
            sources_always_critical=["sec_edgar", "juchao"],
            sentiment_high_magnitude_critical=True,
        ))
    judge = LLMJudge(client=ds, model=snap.app.llm.tier1_model)
    importance = ImportanceClassifier(
        rules=rules, judge=judge,
        gray_zone=tuple(snap.app.classifier.llm_fallback_when_score),  # type: ignore[arg-type]
        watchlist_tickers=[w.ticker for w in snap.watchlist.us]
                          + [w.ticker for w in snap.watchlist.cn],
    )

    pushers = build_pushers(snap.channels, snap.secrets)
    dispatcher = PusherDispatcher(pushers)
    msg_builder = MessageBuilder(source_labels={
        "finnhub": "Finnhub", "sec_edgar": "SEC EDGAR",
        "yfinance_news": "Yahoo", "caixin_telegram": "财联社",
        "akshare_news": "东财", "xueqiu": "雪球", "ths": "同花顺",
        "juchao": "巨潮", "tushare_news": "Tushare",
    })
    burst = BurstSuppressor(
        window_seconds=snap.app.push.same_ticker_burst_window_min * 60,
        threshold=snap.app.push.same_ticker_burst_threshold,
    )
    dispatch_router = DispatchRouter(channels_by_market={
        "us": [c for c, ch in snap.channels.channels.items()
                if ch.market == "us" and ch.enabled],
        "cn": [c for c, ch in snap.channels.channels.items()
                if ch.market == "cn" and ch.enabled],
    })

    archive = None
    if snap.secrets.storage.get("feishu_app_id"):
        us_cli = FeishuBitableClient(
            app_id=snap.secrets.storage["feishu_app_id"],
            app_secret=snap.secrets.storage["feishu_app_secret"],
            app_token=snap.secrets.storage["feishu_app_token"],
            table_id=snap.secrets.storage["feishu_table_us"],
        )
        cn_cli = FeishuBitableClient(
            app_id=snap.secrets.storage["feishu_app_id"],
            app_secret=snap.secrets.storage["feishu_app_secret"],
            app_token=snap.secrets.storage["feishu_app_token"],
            table_id=snap.secrets.storage["feishu_table_cn"],
        )
        archive = ArchiveWriter(clients_by_market={"us": us_cli, "cn": cn_cli})

    bark = None
    if snap.secrets.alert.get("bark_url"):
        bark = BarkAlerter(base_url=snap.secrets.alert["bark_url"])

    dedup = Dedup(raw_dao, title_distance_max=snap.app.dedup.title_simhash_distance)
    sec_ciks: dict[str, str] = {"NVDA": "1045810", "TSLA": "1318605", "AAPL": "320193"}
    scrapers = build_registry(snap.sources, snap.watchlist, snap.secrets,
                                sec_ciks=sec_ciks)

    if once:
        for sid in scrapers.list_ids():
            await scrape_one_source(
                scraper=scrapers.get(sid), dedup=dedup,
                state_dao=state_dao, metrics=metrics,
            )
        await process_pending(
            raw_dao=raw_dao, llm=llm, importance=importance, proc_dao=proc_dao,
            msg_builder=msg_builder, router=dispatch_router, dispatcher=dispatcher,
            push_log=push_log, digest_dao=digest_dao, archive=archive, burst=burst,
        )
        await db.close()
        return

    runner = SchedulerRunner()
    for sid in scrapers.list_ids():
        scraper = scrapers.get(sid)
        src_cfg = snap.sources.sources.get(sid)
        interval = (src_cfg.interval_sec if src_cfg and src_cfg.interval_sec
                    else snap.app.scheduler.scrape.market_hours_interval_sec)
        runner.add_interval(
            name=f"scrape_{sid}", seconds=interval, jitter=10,
            coro_factory=lambda s=scraper: scrape_one_source(
                scraper=s, dedup=dedup, state_dao=state_dao, metrics=metrics),
        )

    runner.add_interval(
        name="process_pending",
        seconds=snap.app.scheduler.llm.process_interval_sec,
        coro_factory=lambda: process_pending(
            raw_dao=raw_dao, llm=llm, importance=importance, proc_dao=proc_dao,
            msg_builder=msg_builder, router=dispatch_router, dispatcher=dispatcher,
            push_log=push_log, digest_dao=digest_dao, archive=archive, burst=burst,
        ),
    )

    # Digest cron jobs (4 per day)
    for key, hm in [("morning_us", snap.app.scheduler.digest.morning_us),
                    ("evening_us", snap.app.scheduler.digest.evening_us),
                    ("morning_cn", snap.app.scheduler.digest.morning_cn),
                    ("evening_cn", snap.app.scheduler.digest.evening_cn)]:
        h, m = map(int, hm.split(":"))
        market = "us" if "us" in key else "cn"
        channels = dispatch_router._by_market.get(market, [])
        runner.add_cron(
            name=f"digest_{key}", hour=h, minute=m,
            coro_factory=lambda k=key, mkt=market, chs=channels:
                _digest_job_runner(k, mkt, chs, digest_dao, proc_dao,
                                    msg_builder, dispatcher),
        )

    runner.start()

    stop_event = asyncio.Event()

    def _on_signal(*_: object) -> None:
        log.info("shutdown_signal")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _on_signal)

    if bark is not None:
        await bark.send("news_pipeline", "started")

    await stop_event.wait()
    await runner.shutdown()
    await db.close()
    log.info("shutdown_complete")


async def _digest_job_runner(
    digest_key: str, market: str, channels: list[str],
    digest_dao: DigestBufferDAO, proc_dao: NewsProcessedDAO,
    msg_builder: MessageBuilder, dispatcher: PusherDispatcher,
) -> int:
    class _DB:
        def build_digest(self, *, items: list, market: str, digest_key: str) -> object:
            from news_pipeline.common.contracts import Badge, CommonMessage
            from news_pipeline.common.enums import Market as _Market
            lines = "\n".join(f"• {p.summary[:120]}" for p in items[:30])
            return CommonMessage(
                title=f"Digest {digest_key}",
                summary=lines or "(no items)",
                source_label="digest",
                source_url="https://news-pipeline.local/",  # type: ignore[arg-type]
                badges=[Badge(text=digest_key, color="blue")],
                chart_url=None,
                deeplinks=[],
                market=_Market(market),
            )

    return await send_digest(
        digest_key=digest_key, market=market, channels=channels,
        digest_dao=digest_dao, proc_dao=proc_dao,
        digest_builder=_DB(), dispatcher=dispatcher,
    )


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
