from datetime import timedelta

from news_pipeline.common.exceptions import AntiCrawlError, ScraperError
from news_pipeline.common.timeutil import utc_now
from news_pipeline.dedup.dedup import Dedup
from news_pipeline.observability.log import get_logger
from news_pipeline.scrapers.base import ScraperProtocol
from news_pipeline.storage.dao.metrics import MetricsDAO
from news_pipeline.storage.dao.source_state import SourceStateDAO

log = get_logger(__name__)


async def scrape_one_source(
    *, scraper: ScraperProtocol, dedup: Dedup,
    state_dao: SourceStateDAO, metrics: MetricsDAO,
    lookback_minutes: int = 60,
) -> int:
    if await state_dao.is_paused(scraper.source_id):
        log.info("scrape_skip_paused", source=scraper.source_id)
        return 0
    state = await state_dao.get(scraper.source_id)
    since = (state.last_fetched_at if state and state.last_fetched_at
             else utc_now().replace(tzinfo=None) - timedelta(minutes=lookback_minutes))
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
        scraper.source_id, last_fetched_at=utc_now().replace(tzinfo=None),
    )
    log.info("scrape_done", source=scraper.source_id,
             new=new_count, total=len(items))
    return new_count
