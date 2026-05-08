from datetime import datetime, timedelta
from typing import Any

import httpx
import requests  # type: ignore[import-untyped]

from news_pipeline.classifier.importance import ImportanceClassifier
from news_pipeline.common.contracts import EnrichedNews, RawArticle
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment
from news_pipeline.common.exceptions import AntiCrawlError
from news_pipeline.common.timeutil import ensure_utc, to_market_local, utc_now
from news_pipeline.dedup.dedup import Dedup
from news_pipeline.llm.pipeline import LLMPipeline
from news_pipeline.observability.alert import AlertLevel, BarkAlerter
from news_pipeline.observability.log import get_logger
from news_pipeline.router.routes import DispatchRouter
from news_pipeline.rules.engine import RulesEngine
from news_pipeline.rules.verdict import RulesVerdict
from news_pipeline.scrapers.base import ScraperProtocol
from news_pipeline.storage.dao.digest_buffer import DigestBufferDAO
from news_pipeline.storage.dao.metrics import MetricsDAO
from news_pipeline.storage.dao.news_processed import NewsProcessedDAO
from news_pipeline.storage.dao.push_log import PushLogDAO
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.dao.source_state import SourceStateDAO
from shared.push.common.burst import BurstSuppressor
from shared.push.common.message_builder import MessageBuilder
from shared.push.dispatcher import PusherDispatcher

log = get_logger(__name__)

# Exception types that indicate transient infrastructure problems:
# retry next interval is fine, no alert needed.
_TRANSIENT_EXC = (
    httpx.TimeoutException,
    httpx.ConnectError,
    # akshare/feedparser sit on top of `requests` — same kind of transient
    # network errors need the same treatment (retry next tick, no alert).
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def synth_enriched_from_rules(
    art: RawArticle, verdict: RulesVerdict, *, raw_id: int
) -> EnrichedNews:
    """Build EnrichedNews from rules match without invoking LLM.

    Rules-only mode: summary = body[:200] truncation. sentiment/magnitude
    default to neutral/low (no LLM inference). model_used='rules-only' so
    push_log + downstream can distinguish.
    """
    body = art.body or ""
    body_excerpt = body[:200].rstrip()
    summary = body_excerpt or art.title

    related = sorted(set(verdict.tickers + verdict.related_tickers))

    return EnrichedNews(
        raw_id=raw_id,
        summary=summary,
        related_tickers=related,
        sectors=list(verdict.sectors),
        event_type=EventType.OTHER,
        sentiment=Sentiment.NEUTRAL,
        magnitude=Magnitude.LOW,
        confidence=0.0,
        key_quotes=[],
        entities=[],
        relations=[],
        model_used="rules-only",
        extracted_at=utc_now().replace(tzinfo=None),
    )


def _is_transient(exc: BaseException) -> bool:
    """Return True if the exception is a known transient network error."""
    return isinstance(exc, _TRANSIENT_EXC) or (
        isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500
    )


def _choose_digest_key(market: Market, now_utc: datetime) -> str:
    """Return 'morning_{market}' or 'evening_{market}' based on local time.

    Rule: if the market-local hour is before 12:00 (noon), it's a morning
    digest; otherwise it's an evening digest.  This ensures articles processed
    during AM hours land in the morning digest and PM/evening articles land in
    the evening digest, so both digest cron jobs actually receive rows.
    """
    local = to_market_local(now_utc, market)
    period = "morning" if local.hour < 12 else "evening"
    return f"{period}_{market.value}"


async def scrape_one_source(
    *,
    scraper: ScraperProtocol,
    dedup: Dedup,
    state_dao: SourceStateDAO,
    metrics: MetricsDAO,
    lookback_minutes: int = 1440,
    bark: BarkAlerter | None = None,
) -> int:
    if await state_dao.is_paused(scraper.source_id):
        log.info("scrape_skip_paused", source=scraper.source_id)
        return 0
    state = await state_dao.get(scraper.source_id)
    # `since` MUST be timezone-aware (UTC). Scrapers compare against datetimes
    # produced by datetime.fromtimestamp(..., tz=UTC) which are aware; mixing
    # naive + aware raises TypeError. SQLite stores naive UTC, so we add tz back.
    raw_since = (
        state.last_fetched_at
        if state and state.last_fetched_at
        else utc_now() - timedelta(minutes=lookback_minutes)
    )
    since = ensure_utc(raw_since)
    try:
        items = await scraper.fetch(since)
    except AntiCrawlError as e:
        log.warning("anticrawl", source=scraper.source_id, error=str(e))
        await state_dao.set_paused(
            scraper.source_id,
            until=utc_now().replace(tzinfo=None) + timedelta(minutes=30),
            error="anti_crawl",
        )
        # C-1: alert on anti-crawl detection (throttled by BarkAlerter)
        if bark is not None:
            await bark.send(
                f"anti_crawl_{scraper.source_id}",
                f"{scraper.source_id} 被反爬, 暂停 30 min",
                level=AlertLevel.WARN,
            )
        return 0
    except Exception as e:
        if _is_transient(e):
            # Transient: HTTP 5xx, timeout, connect error — retry next interval, no alert
            log.warning(
                "scrape_transient_error",
                source=scraper.source_id,
                error=str(e),
                category="transient",
            )
            await state_dao.record_error(scraper.source_id, str(e))
        else:
            # Structural: KeyError, ValueError, AttributeError, parse bug — needs investigation
            log.error(
                "scrape_structural_error",
                source=scraper.source_id,
                error=str(e),
                category="structural",
            )
            await state_dao.record_error(scraper.source_id, str(e))
            if bark is not None:
                await bark.send(
                    f"scrape_structural_{scraper.source_id}",
                    f"{scraper.source_id} 结构错误 (可能是 bug): {str(e)[:150]}",
                    level=AlertLevel.URGENT,
                )
        return 0

    new_count = 0
    for art in items:
        decision = await dedup.check_and_register(art)
        if decision.is_new:
            new_count += 1
        await metrics.increment(
            date_iso=utc_now().date().isoformat(),
            name=("scrape_new" if decision.is_new else "scrape_dup"),
            dimensions=f"source={scraper.source_id}",
        )
    # Watermark = max published_at of returned items (not "now"), so that
    # back-filled items appearing later in the source feed don't get skipped
    # by `ts < since`. URL + simhash dedup handles the small re-overlap.
    new_watermark = (
        max(ensure_utc(it.published_at) for it in items) if items else utc_now()
    )
    await state_dao.update_watermark(
        scraper.source_id,
        last_fetched_at=new_watermark.replace(tzinfo=None),
    )
    log.info("scrape_done", source=scraper.source_id, new=new_count, total=len(items))
    return new_count


def _raw_to_article(row: Any) -> RawArticle:
    return RawArticle(
        source=row.source,
        market=Market(row.market),
        fetched_at=row.fetched_at,
        published_at=row.published_at,
        url=row.url,
        url_hash=row.url_hash,
        title=row.title,
        title_simhash=row.title_simhash,
        body=row.body,
        raw_meta=row.raw_meta or {},
    )


async def process_pending(
    *,
    raw_dao: RawNewsDAO,
    llm: LLMPipeline,
    importance: ImportanceClassifier,
    proc_dao: NewsProcessedDAO,
    msg_builder: MessageBuilder,
    router: DispatchRouter,
    dispatcher: PusherDispatcher,
    push_log: PushLogDAO,
    digest_dao: DigestBufferDAO,
    burst: BurstSuppressor,
    rules_enabled: bool = False,
    llm_enabled: bool = True,
    rules_engine: RulesEngine | None = None,
    batch_size: int = 25,
) -> int:
    """Pull pending raw_news, run pipeline based on rules/llm enable flags.

    4 enable combos (validated by config schema, exactly one branch hit):
    - rules=T,  llm=F: rules-only, synth EnrichedNews from verdict
    - rules=T,  llm=T: rules gates, then LLM enriches matched articles
    - rules=F,  llm=T: classic LLM-only path (Tier-0 classifies)
    - rules=F,  llm=F: rejected at config load (at_least_one_enabled)
    """
    pending = await raw_dao.list_pending(limit=batch_size)
    processed = 0
    for raw in pending:
        if raw.id is None:
            continue
        raw_id: int = raw.id
        art = _raw_to_article(raw)

        # === 1. Rules gate ===
        verdict: RulesVerdict | None = None
        if rules_enabled and rules_engine is not None:
            verdict = rules_engine.match(art)
            if not verdict.matched:
                await raw_dao.mark_status(raw_id, "skipped_rules")
                continue

        # === 2. EnrichedNews source ===
        enriched: Any
        if llm_enabled:
            try:
                if verdict is not None and verdict.matched:
                    enriched = await llm.process_with_rules(art, verdict, raw_id=raw_id)
                else:
                    enriched = await llm.process(art, raw_id=raw_id)
            except Exception as e:
                log.error("llm_failed", raw_id=raw_id, error=str(e))
                await raw_dao.mark_status(raw_id, "dead", error=str(e))
                continue
            if enriched is None:
                await raw_dao.mark_status(raw_id, "skipped")
                continue
        else:
            assert verdict is not None and verdict.matched, (
                "rules-only mode requires rules.enable=True and rules.match=True"
            )
            enriched = synth_enriched_from_rules(art, verdict, raw_id=raw_id)

        # === 3. Score ===
        scored = await importance.score_news(
            enriched,
            source=raw.source,
            verdict=verdict,
        )

        # gray_zone_action='skip' signal → drop without persisting
        if scored.llm_reason == "rules-only-grayzone-skip":
            await raw_dao.mark_status(raw_id, "skipped_grayzone")
            continue

        proc_id = await proc_dao.insert(
            raw_id=raw_id,
            summary=enriched.summary,
            event_type=enriched.event_type.value,
            sentiment=enriched.sentiment.value,
            magnitude=enriched.magnitude.value,
            confidence=enriched.confidence,
            key_quotes=enriched.key_quotes,
            score=scored.score,
            is_critical=scored.is_critical,
            rule_hits=scored.rule_hits,
            llm_reason=scored.llm_reason,
            model_used=enriched.model_used,
            extracted_at=enriched.extracted_at,
        )
        await raw_dao.mark_status(raw_id, "processed")

        # === 4. Render + route + push ===
        if llm_enabled:
            msg = msg_builder.build(art, scored, chart_url=None)
        else:
            assert verdict is not None
            msg = msg_builder.build_from_rules(art, scored, verdict)

        plans = router.route(
            scored,
            msg,
            markets=verdict.markets if verdict is not None else None,
        )

        for p in plans:
            if p.immediate:
                if not burst.should_send(enriched.related_tickers):
                    log.info("push_suppressed_burst", tickers=enriched.related_tickers)
                    continue
                results = await dispatcher.dispatch(p.message, channels=p.channels)
                for ch, r in results.items():
                    await push_log.write(
                        news_id=proc_id,
                        channel=ch,
                        status=("ok" if r.ok else "failed"),
                        http_status=r.http_status,
                        response=r.response_body,
                        retries=r.retries,
                    )
            else:
                await digest_dao.enqueue(
                    news_id=proc_id,
                    market=art.market.value,
                    scheduled_digest=_choose_digest_key(art.market, utc_now()),
                )
                break  # one digest entry per news; channel resolved at digest time

        processed += 1
    return processed


async def send_digest(
    *,
    digest_key: str,
    market: str,
    channels: list[str],
    digest_dao: DigestBufferDAO,
    proc_dao: NewsProcessedDAO,
    digest_builder: Any,
    dispatcher: PusherDispatcher,
) -> int:
    pending = await digest_dao.list_pending(digest_key)
    if not pending:
        return 0
    items = []
    for buf_row in pending:
        proc = await proc_dao.get(buf_row.news_id)
        if proc is not None:
            items.append(proc)
    consumed_ids = [b.id for b in pending if b.id is not None]
    if not items:
        await digest_dao.mark_consumed(consumed_ids)
        return 0
    msg = digest_builder.build_digest(items=items, market=market, digest_key=digest_key)
    await dispatcher.dispatch(msg, channels=channels)
    await digest_dao.mark_consumed(consumed_ids)
    return len(items)


async def alert_on_push_failures(
    *,
    push_log: PushLogDAO,
    bark: BarkAlerter | None,
    threshold: int = 3,
    window_minutes: int = 60,
) -> None:
    """C-4: Check for push channels with repeated failures in the recent window.

    Run every 30 min. If any channel had >= threshold failures in the last
    window_minutes, send a Bark warn.
    """
    if bark is None:
        return
    counts = await push_log.failure_counts_by_channel(window_minutes=window_minutes)
    for channel, count in counts.items():
        if count >= threshold:
            await bark.send(
                f"push_fail_{channel}",
                f"{channel} 最近 {window_minutes} min 推送失败 {count} 次",
                level=AlertLevel.WARN,
            )
