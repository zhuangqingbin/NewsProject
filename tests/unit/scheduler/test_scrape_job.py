from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.scheduler.jobs import scrape_one_source


def _art() -> RawArticle:
    return RawArticle(
        source="finnhub",
        market=Market.US,
        fetched_at=datetime(2026, 4, 25),
        published_at=datetime(2026, 4, 25),
        url="https://x/1",
        url_hash="h",
        title="t",
    )


@pytest.mark.asyncio
async def test_scrape_seeds_first_fetch_and_records_success():
    scraper = MagicMock()
    scraper.source_id = "finnhub"
    scraper.market = Market.US
    scraper.fetch = AsyncMock(return_value=[_art()])

    store = MagicMock(saved_count=1)
    store.save = AsyncMock(return_value=1)
    state_dao = MagicMock()
    state_dao.get = AsyncMock(return_value=None)
    state_dao.is_paused = AsyncMock(return_value=False)
    state_dao.update_watermark = AsyncMock()
    state_dao.record_failure = AsyncMock()
    state_dao.record_success = AsyncMock()
    metrics = MagicMock()
    metrics.increment = AsyncMock()

    n_new = await scrape_one_source(
        scraper=scraper,
        store=store,
        state_dao=state_dao,
        metrics=metrics,
    )
    assert n_new == 1
    state_dao.record_success.assert_awaited_once_with("finnhub", new_items=1)
    store.save.assert_awaited_once_with([_art()], status="seeded")


@pytest.mark.asyncio
async def test_scrape_skips_when_paused():
    scraper = MagicMock()
    scraper.source_id = "x"
    scraper.market = Market.US
    scraper.fetch = AsyncMock()
    store = MagicMock()
    state_dao = MagicMock()
    state_dao.is_paused = AsyncMock(return_value=True)
    metrics = MagicMock()
    metrics.increment = AsyncMock()
    n = await scrape_one_source(scraper=scraper, store=store, state_dao=state_dao, metrics=metrics)
    assert n == 0
    scraper.fetch.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fix I6: error categorization tests
# ---------------------------------------------------------------------------


def _make_state_dao() -> MagicMock:
    dao = MagicMock()
    dao.get = AsyncMock(return_value=None)
    dao.is_paused = AsyncMock(return_value=False)
    dao.record_failure = AsyncMock()
    dao.record_success = AsyncMock()
    dao.set_paused = AsyncMock()
    dao.update_watermark = AsyncMock()
    return dao


def _make_metrics() -> MagicMock:
    m = MagicMock()
    m.increment = AsyncMock()
    return m


@pytest.mark.asyncio
async def test_transient_timeout_no_bark():
    """httpx.TimeoutException → categorized as transient, record_error called, NO Bark."""
    scraper = MagicMock()
    scraper.source_id = "finnhub"
    scraper.fetch = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    bark = MagicMock()
    bark.send = AsyncMock()

    state_dao = _make_state_dao()
    metrics = _make_metrics()

    n = await scrape_one_source(
        scraper=scraper,
        store=MagicMock(),
        state_dao=state_dao,
        metrics=metrics,
        bark=bark,
    )
    assert n == 0
    state_dao.record_failure.assert_awaited_once()
    bark.send.assert_not_awaited()  # transient — no alert


@pytest.mark.asyncio
async def test_transient_http5xx_no_bark():
    """httpx.HTTPStatusError with status 500 → transient, no Bark."""
    scraper = MagicMock()
    scraper.source_id = "cls_telegraph"

    # Build a minimal HTTPStatusError with status 503
    req = httpx.Request("GET", "https://example.com")
    resp = httpx.Response(503, request=req)
    scraper.fetch = AsyncMock(
        side_effect=httpx.HTTPStatusError("Server Error", request=req, response=resp)
    )

    bark = MagicMock()
    bark.send = AsyncMock()

    state_dao = _make_state_dao()
    metrics = _make_metrics()

    n = await scrape_one_source(
        scraper=scraper,
        store=MagicMock(),
        state_dao=state_dao,
        metrics=metrics,
        bark=bark,
    )
    assert n == 0
    state_dao.record_failure.assert_awaited_once()
    bark.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_structural_keyerror_records_health_failure():
    """KeyError → categorized as structural, Bark urgent called."""
    scraper = MagicMock()
    scraper.source_id = "em_stock_news"
    scraper.fetch = AsyncMock(side_effect=KeyError("missing field"))

    bark = MagicMock()
    bark.send = AsyncMock(return_value=True)

    state_dao = _make_state_dao()
    metrics = _make_metrics()

    n = await scrape_one_source(
        scraper=scraper,
        store=MagicMock(),
        state_dao=state_dao,
        metrics=metrics,
        bark=bark,
    )
    assert n == 0
    state_dao.record_failure.assert_awaited_once()
    assert state_dao.record_failure.call_args.kwargs["structural"] is True
    bark.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_structural_no_bark_when_bark_none():
    """Structural error with bark=None → no crash, record_error still called."""
    scraper = MagicMock()
    scraper.source_id = "ths_global"
    scraper.fetch = AsyncMock(side_effect=ValueError("unexpected format"))

    state_dao = _make_state_dao()
    metrics = _make_metrics()

    n = await scrape_one_source(
        scraper=scraper,
        store=MagicMock(),
        state_dao=state_dao,
        metrics=metrics,
        bark=None,
    )
    assert n == 0
    state_dao.record_failure.assert_awaited_once()
