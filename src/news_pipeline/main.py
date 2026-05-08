from __future__ import annotations

import asyncio
import os
import signal
from datetime import timedelta
from pathlib import Path

from news_pipeline.classifier.importance import ImportanceClassifier
from news_pipeline.classifier.llm_judge import LLMJudge
from news_pipeline.classifier.rules import RuleEngine
from news_pipeline.common.timeutil import utc_now
from news_pipeline.config.loader import ConfigLoader
from news_pipeline.config.schema import ClassifierRulesCfg
from news_pipeline.dedup.dedup import Dedup
from news_pipeline.llm.client_selection import is_anthropic_configured, pick_client_and_model
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
from news_pipeline.router.routes import DispatchRouter
from news_pipeline.rules.engine import RulesEngine
from news_pipeline.rules.matcher import build_matcher
from news_pipeline.scheduler.jobs import (
    alert_on_push_failures,
    process_pending,
    scrape_one_source,
)
from news_pipeline.scheduler.runner import SchedulerRunner
from news_pipeline.scrapers.factory import build_registry
from news_pipeline.scrapers.registry import ScraperRegistry
from news_pipeline.storage.dao.audit_log import AuditLogDAO
from news_pipeline.storage.dao.dead_letter import DeadLetterDAO
from news_pipeline.storage.dao.digest_buffer import DigestBufferDAO
from news_pipeline.storage.dao.metrics import MetricsDAO
from news_pipeline.storage.dao.news_processed import NewsProcessedDAO
from news_pipeline.storage.dao.push_log import PushLogDAO
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.dao.source_state import SourceStateDAO
from news_pipeline.storage.db import Database
from shared.observability.alert import AlertLevel, BarkAlerter
from shared.observability.log import configure_logging, get_logger
from shared.observability.weekly_report import build_dlq_summary
from shared.push.common.burst import BurstSuppressor
from shared.push.common.message_builder import MessageBuilder
from shared.push.dispatcher import PusherDispatcher
from shared.push.factory import build_pushers

PRICING = {
    "deepseek-v3": ModelPricing(input_per_m_cny=0.5, output_per_m_cny=1.5),
    "claude-haiku-4-5-20251001": ModelPricing(input_per_m_cny=7.0, output_per_m_cny=35.0),
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

    # LLM clients
    ds = DashScopeClient(api_key=snap.secrets.llm.get("dashscope_api_key", ""))

    anthropic_key = snap.secrets.llm.get("anthropic_api_key", "").strip()
    has_anthropic = is_anthropic_configured(anthropic_key)
    cl: AnthropicClient | None = AnthropicClient(api_key=anthropic_key) if has_anthropic else None

    if not has_anthropic:
        log.warning(
            "anthropic_not_configured_fallback_to_tier1",
            tier2_configured=snap.app.llm.tier2_model,
            tier3_configured=snap.app.llm.tier3_model,
            fallback_model=snap.app.llm.tier1_model,
        )

    prompts = PromptLoader(cfg_dir / "prompts")
    p_versions = snap.app.llm.prompt_versions
    # CostTracker gets bark reference after bark is built (bark may be None if not configured)
    # bark is built later; we pass it after building. Use a placeholder and update below.
    cost = CostTracker(daily_ceiling_cny=snap.app.runtime.daily_cost_ceiling_cny, pricing=PRICING)

    tier2_client, tier2_model = pick_client_and_model(
        snap.app.llm.tier2_model,
        anthropic_client=cl,
        dashscope_client=ds,
        tier1_fallback_model=snap.app.llm.tier1_model,
    )
    _tier3_client, _tier3_model = pick_client_and_model(
        snap.app.llm.tier3_model,
        anthropic_client=cl,
        dashscope_client=ds,
        tier1_fallback_model=snap.app.llm.tier1_model,
    )

    tier0 = Tier0Classifier(
        client=ds,
        prompt=prompts.load("tier0_classify", p_versions["tier0_classify"]),
        cost=cost,
    )
    tier1 = Tier1Summarizer(
        client=ds,
        prompt=prompts.load("tier1_summarize", p_versions["tier1_summarize"]),
        cost=cost,
    )
    tier2 = Tier2DeepExtractor(
        client=tier2_client,
        prompt=prompts.load("tier2_extract", p_versions["tier2_extract"]),
        cost=cost,
        model_override=tier2_model,
    )
    llm_router = LLMRouter(first_party_sources={"sec_edgar", "juchao", "caixin_telegram"})
    llm = LLMPipeline(
        tier0,
        tier1,
        tier2,
        llm_router,
        cost,
        watchlist_us=snap.watchlist.effective_us(),
        watchlist_cn=snap.watchlist.effective_cn(),
        first_party_sources={"sec_edgar", "juchao", "caixin_telegram"},
    )

    # === v0.3.0 RulesEngine ===
    rules_enabled = snap.watchlist.rules.enable
    llm_enabled = snap.watchlist.llm.enable
    rules_engine: RulesEngine | None = None
    if rules_enabled:
        matcher = build_matcher(
            snap.watchlist.rules.matcher,
            snap.watchlist.rules.matcher_options,
        )
        rules_engine = RulesEngine(snap.watchlist.rules, matcher)
        log.info(
            "rules_engine_built",
            us_tickers=len(snap.watchlist.rules.us),
            cn_tickers=len(snap.watchlist.rules.cn),
            matcher=snap.watchlist.rules.matcher,
        )

    if snap.app.classifier.rules:
        rules = RuleEngine(snap.app.classifier.rules)
    else:
        rules = RuleEngine(
            ClassifierRulesCfg(
                price_move_critical_pct=5.0,
                sources_always_critical=["sec_edgar", "juchao"],
                sentiment_high_magnitude_critical=True,
            )
        )
    judge = LLMJudge(client=ds, model=snap.app.llm.tier1_model)
    importance = ImportanceClassifier(
        rules=rules,
        judge=judge,
        gray_zone=tuple(snap.app.classifier.llm_fallback_when_score),  # type: ignore[arg-type]
        watchlist_tickers=snap.watchlist.effective_us() + snap.watchlist.effective_cn(),
        gray_zone_action=snap.watchlist.rules.gray_zone_action,
        llm_enabled=llm_enabled,
    )

    pushers = build_pushers(snap.channels, snap.secrets)
    dispatcher = PusherDispatcher(pushers)
    msg_builder = MessageBuilder(
        source_labels={
            "finnhub": "Finnhub",
            "sec_edgar": "SEC EDGAR",
            "yfinance_news": "Yahoo",
            "futu_global": "富途",
            "wallstreetcn": "华尔街见闻",
            "caixin_telegram": "财联社",
            "eastmoney_global": "东财快讯",
            "akshare_news": "东财",
            "ths_global": "同花顺",
            "sina_global": "新浪财经",
            "cjzc_em": "财经早餐",
            "cctv_news": "新闻联播",
            "kr36": "36氪",
            "xueqiu": "雪球",
            "ths": "同花顺",
            "juchao": "巨潮",
            "tushare_news": "Tushare",
        }
    )
    burst = BurstSuppressor(
        window_seconds=snap.app.push.same_ticker_burst_window_min * 60,
        threshold=snap.app.push.same_ticker_burst_threshold,
    )
    dispatch_router = DispatchRouter(
        channels_by_market={
            "us": [
                c for c, ch in snap.channels.channels.items() if ch.market == "us" and ch.enabled
            ],
            "cn": [
                c for c, ch in snap.channels.channels.items() if ch.market == "cn" and ch.enabled
            ],
        }
    )

    bark = None
    if snap.secrets.alert.get("bark_url"):
        bark = BarkAlerter(base_url=snap.secrets.alert["bark_url"])

    # C-2/C-3: wire bark into cost tracker now that bark is available
    cost._bark = bark

    dedup = Dedup(raw_dao, title_distance_max=snap.app.dedup.title_simhash_distance)
    sec_ciks: dict[str, str] = {"NVDA": "1045810", "TSLA": "1318605", "AAPL": "320193"}
    scrapers = build_registry(snap.sources, snap.watchlist, snap.secrets, sec_ciks=sec_ciks)

    if once:
        for sid in scrapers.list_ids():
            await scrape_one_source(
                scraper=scrapers.get(sid),
                dedup=dedup,
                state_dao=state_dao,
                metrics=metrics,
                bark=bark,
            )
        await process_pending(
            raw_dao=raw_dao,
            llm=llm,
            importance=importance,
            proc_dao=proc_dao,
            msg_builder=msg_builder,
            router=dispatch_router,
            dispatcher=dispatcher,
            push_log=push_log,
            digest_dao=digest_dao,
            burst=burst,
            rules_enabled=rules_enabled,
            llm_enabled=llm_enabled,
            rules_engine=rules_engine,
        )
        await db.close()
        return

    runner = SchedulerRunner()
    for sid in scrapers.list_ids():
        scraper = scrapers.get(sid)
        src_cfg = snap.sources.sources.get(sid)
        interval = (
            src_cfg.interval_sec
            if src_cfg and src_cfg.interval_sec
            else snap.app.scheduler.scrape.market_hours_interval_sec
        )
        runner.add_interval(
            name=f"scrape_{sid}",
            seconds=interval,
            jitter=10,
            coro_factory=lambda s=scraper: scrape_one_source(  # type: ignore[misc]
                scraper=s, dedup=dedup, state_dao=state_dao, metrics=metrics, bark=bark
            ),
        )

    runner.add_interval(
        name="process_pending",
        seconds=snap.app.scheduler.llm.process_interval_sec,
        coro_factory=lambda: process_pending(
            raw_dao=raw_dao,
            llm=llm,
            importance=importance,
            proc_dao=proc_dao,
            msg_builder=msg_builder,
            router=dispatch_router,
            dispatcher=dispatcher,
            push_log=push_log,
            digest_dao=digest_dao,
            burst=burst,
            rules_enabled=rules_enabled,
            llm_enabled=llm_enabled,
            rules_engine=rules_engine,
        ),
    )

    # Digest cron jobs (4 per day)
    for key, hm in [
        ("morning_us", snap.app.scheduler.digest.morning_us),
        ("evening_us", snap.app.scheduler.digest.evening_us),
        ("morning_cn", snap.app.scheduler.digest.morning_cn),
        ("evening_cn", snap.app.scheduler.digest.evening_cn),
    ]:
        h, m = map(int, hm.split(":"))
        market = "us" if "us" in key else "cn"
        channels = dispatch_router._by_market.get(market, [])
        runner.add_cron(
            name=f"digest_{key}",
            hour=h,
            minute=m,
            coro_factory=lambda k=key, mkt=market, chs=channels: _digest_job_runner(  # type: ignore[misc]
                k, mkt, chs, digest_dao, proc_dao, raw_dao, msg_builder, dispatcher
            ),
        )

    # B-I11: startup connectivity probe — warns immediately if any source is broken
    await _probe_scrapers(scrapers, bark)

    # C-4: push failure threshold alert (every 30 min)
    runner.add_interval(
        name="push_failure_alert",
        seconds=1800,
        coro_factory=lambda: alert_on_push_failures(push_log=push_log, bark=bark),
    )

    # C-6: daily heartbeat — if you go 24h without seeing this, something is wrong
    async def _heartbeat() -> None:
        if bark is not None:
            await bark.send("heartbeat", "news_pipeline alive", level=AlertLevel.INFO)

    runner.add_interval(
        name="bark_heartbeat",
        seconds=86400,
        coro_factory=_heartbeat,
    )

    # C-7: weekly DLQ summary (Mon 08:00 CST)
    async def _weekly_dlq_alert() -> None:
        if bark is None:
            return
        summary = await build_dlq_summary(dlq=_dlq)
        if summary:
            await bark.send(
                "dlq_weekly_summary",
                f"未处理死信:\n{summary}"[:200],
                level=AlertLevel.INFO,
            )

    runner.add_cron(
        name="dlq_weekly_alert",
        hour=8,
        minute=0,
        coro_factory=_weekly_dlq_alert,
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
    try:
        await asyncio.wait_for(runner.shutdown(), timeout=30)
    except TimeoutError:
        log.error("shutdown_timeout", waited_seconds=30)
    await db.close()
    log.info("shutdown_complete")


async def _probe_scrapers(reg: ScraperRegistry, bark: BarkAlerter | None) -> None:
    """Quick connectivity check for each enabled scraper at startup.

    Logs warnings on failure; does NOT crash the pipeline.
    Bark-warns if any scraper is unreachable so user knows within 1 min of restart
    instead of silently producing 0 items for hours.
    """
    for sid in reg.list_ids():
        scraper = reg.get(sid)
        try:
            since = utc_now() - timedelta(
                minutes=5
            )  # aware UTC; scrapers compare against tz-aware ts
            items = await asyncio.wait_for(scraper.fetch(since), timeout=15)
            log.info("scraper_probe_ok", source=sid, items=len(items))
        except Exception as e:
            log.warning("scraper_probe_failed", source=sid, error=str(e))
            if bark is not None:
                await bark.send(
                    f"scraper_probe_{sid}_failed",
                    str(e)[:200],
                    level=AlertLevel.WARN,
                )


_DIGEST_TITLE = {"us": "美股星盘", "cn": "A股星盘"}


async def _digest_job_runner(
    digest_key: str,
    market: str,
    channels: list[str],
    digest_dao: DigestBufferDAO,
    proc_dao: NewsProcessedDAO,
    raw_dao: RawNewsDAO,
    msg_builder: MessageBuilder,
    dispatcher: PusherDispatcher,
) -> int:
    from news_pipeline.common.contracts import (
        Badge,
        CommonMessage,
        DigestItem,
    )
    from news_pipeline.common.enums import Market as _Market

    title = _DIGEST_TITLE.get(market, market)

    pending = await digest_dao.list_pending(digest_key)
    if not pending:
        return 0
    consumed_ids = [b.id for b in pending if b.id is not None]

    digest_items: list[DigestItem] = []
    for buf_row in pending[:30]:
        proc = await proc_dao.get(buf_row.news_id)
        if proc is None:
            continue
        raw = await raw_dao.get(proc.raw_id)
        if raw is None:
            continue
        digest_items.append(
            DigestItem(
                source_label=msg_builder.label_for(raw.source),
                url=raw.url,
                summary=proc.summary[:120],
            )
        )

    if not digest_items:
        await digest_dao.mark_consumed(consumed_ids)
        return 0

    msg = CommonMessage(
        title=title,
        summary="",
        source_label=title,
        source_url="https://news-pipeline.local/",
        badges=[Badge(text=digest_key, color="blue")],
        chart_url=None,
        deeplinks=[],
        market=_Market(market),
        digest_items=digest_items,
    )
    await dispatcher.dispatch(msg, channels=channels)
    await digest_dao.mark_consumed(consumed_ids)
    return len(digest_items)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
