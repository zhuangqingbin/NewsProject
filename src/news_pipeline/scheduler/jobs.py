import asyncio
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import requests
from curl_cffi.curl import CurlError

from news_pipeline.classifier.importance import ImportanceClassifier
from news_pipeline.common.contracts import EnrichedNews, RawArticle
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment
from news_pipeline.common.exceptions import AntiCrawlError
from news_pipeline.common.timeutil import ensure_utc, to_market_local, utc_now
from news_pipeline.config.schema import DigestCfg, PushCfg, SourceDef
from news_pipeline.dedup.dedup import Dedup
from news_pipeline.events.sent_cache import SentEventCache
from news_pipeline.events.similarity import Features, features, same_event
from news_pipeline.ingest.store import ArticleStore
from news_pipeline.llm.pipeline import LLMPipeline
from news_pipeline.router.routes import DispatchRouter
from news_pipeline.rules.engine import RulesEngine
from news_pipeline.rules.headline import headline
from news_pipeline.rules.verdict import RulesVerdict
from news_pipeline.scrapers.base import ScraperProtocol
from news_pipeline.storage.dao.deliveries import DeliveryDAO
from news_pipeline.storage.dao.digest_buffer import DigestBufferDAO
from news_pipeline.storage.dao.metrics import MetricsDAO
from news_pipeline.storage.dao.news_processed import NewsProcessedDAO
from news_pipeline.storage.dao.push_log import PushLogDAO
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.dao.source_state import SourceStateDAO
from news_pipeline.storage.models import DigestBuffer, NewsProcessed, RawNews
from shared.common.contracts import DigestItem
from shared.observability.alert import AlertLevel, BarkAlerter
from shared.observability.log import get_logger
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
    # akshare's modern transport is curl_cffi (TLS fingerprint impersonation);
    # raw curl-level failures like CURLE_OPERATION_TIMEDOUT (28) surface as
    # CurlError("Failed to perform, curl: (28) Operation timed out...") and
    # are network transients, not bugs.
    CurlError,
)


def synth_enriched_from_rules(
    art: RawArticle, verdict: RulesVerdict, *, raw_id: int
) -> EnrichedNews:
    """Build EnrichedNews from rules match without invoking LLM.

    Rules-only mode: summary = body[:200] truncation. sentiment/magnitude
    default to neutral/low (no LLM inference). model_used='rules-only' so
    push_log + downstream can distinguish.
    """
    summary = headline(art.title, art.body)

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


async def _scrape_with_legacy_dedup(
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
    new_watermark = max(ensure_utc(it.published_at) for it in items) if items else utc_now()
    await state_dao.update_watermark(
        scraper.source_id,
        last_fetched_at=new_watermark.replace(tzinfo=None),
    )
    log.info("scrape_done", source=scraper.source_id, new=new_count, total=len(items))
    return new_count


async def scrape_one_source(
    *,
    scraper: ScraperProtocol,
    state_dao: SourceStateDAO,
    store: ArticleStore | None = None,
    cfg: SourceDef | None = None,
    metrics: MetricsDAO | None = None,
    bark: BarkAlerter | None = None,
    dedup: Dedup | None = None,
) -> int:
    if store is None:
        assert dedup is not None and metrics is not None
        return await _scrape_with_legacy_dedup(
            scraper=scraper, dedup=dedup, state_dao=state_dao, metrics=metrics, bark=bark
        )
    source_cfg = cfg or SourceDef()
    sid = scraper.source_id
    if await state_dao.is_paused(sid):
        return 0
    since = utc_now() - timedelta(minutes=source_cfg.lookback_min)
    try:
        items = await asyncio.wait_for(scraper.fetch(since), timeout=source_cfg.fetch_timeout_sec)
        state = await state_dao.get(sid)
        first = state is None or state.last_success_at is None
        count = await store.save(items, status="seeded" if first else "pending")
    except Exception as error:
        await state_dao.record_failure(
            sid,
            error=repr(error),
            structural=not _is_transient(error),
            base_interval=source_cfg.interval_sec or 60,
        )
        log.warning("scrape_failed", source=sid, error=repr(error))
        return 0
    await state_dao.record_success(sid, new_items=store.saved_count)
    if metrics is not None:
        await metrics.increment(
            date_iso=utc_now().date().isoformat(),
            name="scrape_new",
            dimensions=f"source={sid}",
            delta=count,
        )
    log.info("scrape_done", source=sid, new=count, total=len(items), seeded=first)
    return count


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
    llm: LLMPipeline | None,
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
    push_cfg: PushCfg | None = None,
    sent_cache: SentEventCache | None = None,
    announcement_window_min: int = 10,
    announcement_max_items: int = 5,
) -> int:
    """Pull pending raw_news, run pipeline based on rules/llm enable flags.

    4 enable combos (validated by config schema, exactly one branch hit):
    - rules=T,  llm=F: rules-only, synth EnrichedNews from verdict
    - rules=T,  llm=T: rules gates, then LLM enriches matched articles
    - rules=F,  llm=T: classic LLM-only path (Tier-0 classifies)
    - rules=F,  llm=F: rejected at config load (at_least_one_enabled)
    """
    pending = await raw_dao.list_pending(limit=batch_size)
    groups: list[list[Any]] = []
    if rules_enabled and rules_engine is not None:
        for raw in pending:
            if raw.source != "juchao" or raw.id is None:
                continue
            group_verdict = rules_engine.match(_raw_to_article(raw))
            if group_verdict.reason != "tier:high":
                continue
            group = next(
                (
                    g
                    for g in groups
                    if len(g) < announcement_max_items
                    and rules_engine.match(_raw_to_article(g[0])).subject_tickers
                    == group_verdict.subject_tickers
                    and abs(
                        (
                            ensure_utc(raw.published_at) - ensure_utc(g[0].published_at)
                        ).total_seconds()
                    )
                    <= announcement_window_min * 60
                ),
                None,
            )
            if group is None:
                groups.append([raw])
            else:
                group.append(raw)
    group_by_raw = {r.id: g for g in groups for r in g}
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
                await raw_dao.mark_status(
                    raw_id, "skipped_low" if verdict.reason == "tier:low" else "skipped_rules"
                )
                continue

        # === 2. EnrichedNews source ===
        enriched: Any
        if llm_enabled:
            assert llm is not None
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

        announcement_group = group_by_raw.get(raw_id, [])
        if announcement_group and announcement_group[0].id != raw_id:
            await proc_dao.mark_push_status(proc_id, "dup")
            processed += 1
            continue

        # === 4. Render + route + push ===
        if llm_enabled:
            msg = msg_builder.build(art, scored, chart_url=None)
        else:
            assert verdict is not None
            msg = msg_builder.build_from_rules(art, scored, verdict)

        if len(announcement_group) > 1:
            name = announcement_group[0].title.split("：", 1)[0]  # noqa: RUF001
            msg = msg.model_copy(
                update={
                    "title": f"{name} 发布 {len(announcement_group)} 份公告",
                    "digest_items": [
                        DigestItem(
                            source_label="公告",
                            url=row.url,
                            summary=headline(row.title, row.body)[:60],
                        )
                        for row in announcement_group
                    ],
                }
            )

        plans = router.route(
            scored,
            msg,
            markets=verdict.markets if verdict is not None else None,
        )

        subject_tickers = (
            verdict.subject_tickers if verdict is not None else enriched.related_tickers
        )
        feature = features(
            headline(art.title, art.body), subject_tickers, ensure_utc(art.published_at)
        )
        downgrade: str | None = None
        if any(p.immediate for p in plans):
            if sent_cache is not None and sent_cache.duplicate(feature):
                downgrade = "dup"
            elif (
                push_cfg is not None
                and raw.source not in {"juchao", "sec_edgar"}
                and (utc_now() - ensure_utc(art.published_at)).total_seconds()
                > push_cfg.max_age_min * 60
            ):
                downgrade = "stale_digest"
            elif push_cfg is not None and _legacy_quiet(push_cfg, verdict):
                downgrade = "quiet_digest"
            elif not burst.should_send(subject_tickers):
                downgrade = "burst_digest"
        needs_digest = bool(downgrade) or not any(p.immediate for p in plans)
        successful = False
        if not downgrade:
            for p in plans:
                if not p.immediate:
                    continue
                results = await dispatcher.dispatch(p.message, channels=p.channels)
                for ch, r in results.items():
                    await push_log.write(
                        news_id=proc_id,
                        channel=ch,
                        status="ok" if r.ok else "failed",
                        http_status=r.http_status,
                        response=r.response_body,
                        retries=r.retries,
                    )
                successful |= any(r.ok for r in results.values())
                if not results or not all(r.ok for r in results.values()):
                    needs_digest = True
        if successful and sent_cache is not None:
            sent_cache.record(feature)
        if needs_digest:
            market = (
                verdict.markets[0] if verdict is not None and verdict.markets else art.market.value
            )
            await digest_dao.enqueue(news_id=proc_id, market=market, scheduled_digest=market)
        await proc_dao.mark_push_status(proc_id, downgrade or ("sent" if successful else "digest"))

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
    results = await dispatcher.dispatch(msg, channels=channels)
    if results and all(channel in results and results[channel].ok for channel in channels):
        await digest_dao.mark_consumed(consumed_ids)
        return len(items)
    return 0


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


def _legacy_quiet(cfg: PushCfg, verdict: RulesVerdict | None) -> bool:
    quiet = cfg.quiet_hours
    if not quiet.enabled or (verdict is not None and verdict.reason in quiet.allow_reasons):
        return False
    current = utc_now().astimezone(ZoneInfo(quiet.tz)).strftime("%H:%M")
    if quiet.start <= quiet.end:
        return quiet.start <= current < quiet.end
    return current >= quiet.start or current < quiet.end


async def run_legacy_digest(
    *,
    market: str,
    channels: list[str],
    digest_dao: DigestBufferDAO,
    proc_dao: NewsProcessedDAO,
    raw_dao: RawNewsDAO,
    msg_builder: MessageBuilder,
    dispatcher: PusherDispatcher,
    cfg: DigestCfg,
    rules_engine: RulesEngine | None = None,
    deliveries: DeliveryDAO | None = None,
    slot: str | None = None,
) -> int:
    pending = await digest_dao.list_pending_market(market)
    candidates = []
    expired = []
    now = utc_now()
    for buffer in pending:
        proc = await proc_dao.get(buffer.news_id)
        raw = await raw_dao.get(proc.raw_id) if proc else None
        if (
            raw is None
            or proc is None
            or now - ensure_utc(raw.published_at) > timedelta(hours=cfg.max_age_hours)
        ):
            if buffer.id is not None:
                expired.append(buffer.id)
            continue
        candidates.append((buffer, proc, raw))
    if expired:
        await digest_dao.mark_consumed(expired)
    if not candidates or not channels:
        return 0
    candidates.sort(key=lambda value: (value[1].score, value[2].published_at), reverse=True)
    selected = []
    fs: list[Features] = []
    for entry in candidates:
        subjects = (
            rules_engine.match(_raw_to_article(entry[2])).subject_tickers if rules_engine else []
        )
        f = features(
            headline(entry[2].title, entry[2].body), subjects, ensure_utc(entry[2].published_at)
        )
        if not any(same_event(f, prior) for prior in fs):
            selected.append(entry)
            fs.append(f)
        if len(selected) >= cfg.max_items:
            break
    first = _raw_to_article(selected[0][2])
    from news_pipeline.deliver.cards import trim_message
    from shared.common.contracts import Badge, CommonMessage

    def holdings_related(entry: tuple[DigestBuffer, NewsProcessed, RawNews]) -> bool:
        if entry[1].push_status in {
            "dup",
            "burst_digest",
            "stale_digest",
            "quiet_digest",
        }:
            return True
        if rules_engine is not None:
            return rules_engine.match(_raw_to_article(entry[2])).decision in {"push", "digest_hi"}
        return entry[1].score >= 60

    selected.sort(key=lambda value: not holdings_related(value))
    msg = CommonMessage(
        title="A股简报" if market == "cn" else "美股简报",
        summary="自选相关 · 宏观与行业",
        source_label="简报",
        source_url=first.url,
        market=Market(market),
        badges=[Badge(text="简报")],
        chart_url=None,
        deeplinks=[],
        kind="digest",
        digest_items=[
            DigestItem(
                source_label=entry[2].source,
                url=entry[2].url,
                summary=headline(entry[2].title, entry[2].body)[:60],
                section="自选相关" if holdings_related(entry) else "宏观与行业",
            )
            for entry in selected
        ],
    )
    msg = trim_message(msg)
    results = await dispatcher.dispatch(msg, channels=channels)
    if deliveries is not None:
        from news_pipeline.storage.models import Delivery

        for channel in channels:
            success = channel in results and results[channel].ok
            await deliveries.enqueue(
                Delivery(
                    kind="legacy_digest",
                    market=market,
                    channel=channel,
                    digest_slot=slot or now.isoformat(),
                    event_ids=[entry[1].id for entry in selected[: len(msg.digest_items)]],
                    payload=msg.model_dump(mode="json"),
                    status="sent" if success else "legacy_failed",
                    sent_at=now.replace(tzinfo=None) if success else None,
                )
            )
    if not results or not all(channel in results and results[channel].ok for channel in channels):
        return 0
    await digest_dao.mark_consumed([entry[0].id for entry in candidates if entry[0].id is not None])
    return len(msg.digest_items)
