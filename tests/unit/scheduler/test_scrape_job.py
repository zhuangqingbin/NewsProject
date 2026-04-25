from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.scheduler.jobs import scrape_one_source


def _art() -> RawArticle:
    return RawArticle(
        source="finnhub", market=Market.US,
        fetched_at=datetime(2026, 4, 25), published_at=datetime(2026, 4, 25),
        url="https://x/1", url_hash="h", title="t",
    )


@pytest.mark.asyncio
async def test_scrape_dedup_writes_pending():
    scraper = MagicMock(); scraper.source_id = "finnhub"
    scraper.market = Market.US
    scraper.fetch = AsyncMock(return_value=[_art()])

    dedup = MagicMock()
    dedup.check_and_register = AsyncMock(return_value=MagicMock(
        is_new=True, raw_id=42, reason=None,
    ))
    state_dao = MagicMock()
    state_dao.get = AsyncMock(return_value=None)
    state_dao.is_paused = AsyncMock(return_value=False)
    state_dao.update_watermark = AsyncMock()
    state_dao.record_error = AsyncMock()
    metrics = MagicMock(); metrics.increment = AsyncMock()

    n_new = await scrape_one_source(
        scraper=scraper, dedup=dedup, state_dao=state_dao, metrics=metrics,
    )
    assert n_new == 1
    state_dao.update_watermark.assert_awaited_once()


@pytest.mark.asyncio
async def test_scrape_skips_when_paused():
    scraper = MagicMock(); scraper.source_id = "x"; scraper.market = Market.US
    scraper.fetch = AsyncMock()
    dedup = MagicMock()
    state_dao = MagicMock()
    state_dao.is_paused = AsyncMock(return_value=True)
    metrics = MagicMock(); metrics.increment = AsyncMock()
    n = await scrape_one_source(scraper=scraper, dedup=dedup,
                                 state_dao=state_dao, metrics=metrics)
    assert n == 0
    scraper.fetch.assert_not_awaited()
