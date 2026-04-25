from datetime import timedelta
from typing import Any

from news_pipeline.archive.schema import enriched_to_row
from news_pipeline.archive.writer import ArchiveWriter
from news_pipeline.classifier.importance import ImportanceClassifier
from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.exceptions import AntiCrawlError, ScraperError
from news_pipeline.common.timeutil import utc_now
from news_pipeline.dedup.dedup import Dedup
from news_pipeline.llm.pipeline import LLMPipeline
from news_pipeline.observability.log import get_logger
from news_pipeline.pushers.common.burst import BurstSuppressor
from news_pipeline.pushers.common.message_builder import MessageBuilder
from news_pipeline.pushers.dispatcher import PusherDispatcher
from news_pipeline.router.routes import DispatchRouter
from news_pipeline.scrapers.base import ScraperProtocol
from news_pipeline.storage.dao.digest_buffer import DigestBufferDAO
from news_pipeline.storage.dao.metrics import MetricsDAO
from news_pipeline.storage.dao.news_processed import NewsProcessedDAO
from news_pipeline.storage.dao.push_log import PushLogDAO
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.dao.source_state import SourceStateDAO

log = get_logger(__name__)


async def scrape_one_source(
    *,
    scraper: ScraperProtocol,
    dedup: Dedup,
    state_dao: SourceStateDAO,
    metrics: MetricsDAO,
    lookback_minutes: int = 60,
) -> int:
    if await state_dao.is_paused(scraper.source_id):
        log.info("scrape_skip_paused", source=scraper.source_id)
        return 0
    state = await state_dao.get(scraper.source_id)
    since = (
        state.last_fetched_at
        if state and state.last_fetched_at
        else utc_now().replace(tzinfo=None) - timedelta(minutes=lookback_minutes)
    )
    try:
        items = await scraper.fetch(since)
    except AntiCrawlError as e:
        log.warning("anticrawl", source=scraper.source_id, error=str(e))
        await state_dao.set_paused(
            scraper.source_id,
            until=utc_now().replace(tzinfo=None) + timedelta(minutes=30),
            error="anti_crawl",
        )
        return 0
    except (ScraperError, Exception) as e:
        log.error("scrape_failed", source=scraper.source_id, error=str(e))
        await state_dao.record_error(scraper.source_id, str(e))
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
    await state_dao.update_watermark(
        scraper.source_id,
        last_fetched_at=utc_now().replace(tzinfo=None),
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
    archive: ArchiveWriter | None,
    burst: BurstSuppressor,
    archive_enabled: bool = True,
    batch_size: int = 25,
) -> int:
    pending = await raw_dao.list_pending(limit=batch_size)
    processed = 0
    for raw in pending:
        if raw.id is None:
            continue
        raw_id: int = raw.id
        art = _raw_to_article(raw)
        try:
            enriched = await llm.process(art, raw_id=raw_id)
        except Exception as e:
            log.error("llm_failed", raw_id=raw_id, error=str(e))
            await raw_dao.mark_status(raw_id, "dead", error=str(e))
            continue
        if enriched is None:
            await raw_dao.mark_status(raw_id, "skipped")
            continue

        scored = await importance.score_news(enriched, source=raw.source)
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

        msg = msg_builder.build(art, scored, chart_url=None)
        plans = router.route(scored, msg)
        sent_to: list[str] = []

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
                    if r.ok:
                        sent_to.append(ch)
            else:
                for _ch in p.channels:
                    await digest_dao.enqueue(
                        news_id=proc_id,
                        market=art.market.value,
                        scheduled_digest=f"morning_{art.market.value}",
                    )
                    break  # one entry per news enough; channel resolved at digest time

        if archive is not None and archive_enabled:
            try:
                row = enriched_to_row(
                    art,
                    scored,
                    news_processed_id=proc_id,
                    sent_to=sent_to,
                    chart_url=str(msg.chart_url) if msg.chart_url else None,
                )
                await archive.write(market=art.market.value, row=row)
            except Exception as e:
                log.warning("archive_failed", news_id=proc_id, error=str(e))

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
