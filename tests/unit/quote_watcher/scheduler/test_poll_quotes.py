from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.scheduler.jobs import poll_quotes
from quote_watcher.store.tick import TickRing

BJ = ZoneInfo("Asia/Shanghai")


@pytest.mark.asyncio
async def test_poll_quotes_skips_when_market_closed():
    feed = AsyncMock()
    cal = MarketCalendar()
    ring = TickRing()
    closed_dt = datetime(2026, 5, 9, 10, 0, tzinfo=BJ)  # Saturday
    n = await poll_quotes(
        feed=feed, calendar=cal, ring=ring,
        tickers=[("SH", "600519")],
        now=closed_dt,
    )
    assert n == 0
    feed.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_poll_quotes_appends_to_ring():
    snap = QuoteSnapshot(
        ticker="600519", market="SH", name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=1789.5, open=1820, high=1825, low=1788, prev_close=1815.5,
        volume=100, amount=1.0, bid1=1789.5, ask1=1789.6,
    )
    feed = AsyncMock()
    feed.fetch.return_value = [snap]
    cal = MarketCalendar()
    ring = TickRing()

    open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)  # Friday morning
    n = await poll_quotes(
        feed=feed, calendar=cal, ring=ring,
        tickers=[("SH", "600519")],
        now=open_dt,
    )
    assert n == 1
    assert ring.latest("600519").price == 1789.5
    feed.fetch.assert_awaited_once_with([("SH", "600519")])


@pytest.mark.asyncio
async def test_poll_quotes_handles_empty_response():
    feed = AsyncMock()
    feed.fetch.return_value = []
    cal = MarketCalendar()
    ring = TickRing()
    n = await poll_quotes(
        feed=feed, calendar=cal, ring=ring,
        tickers=[("SH", "600519")],
        now=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
    )
    assert n == 0
    assert ring.size("600519") == 0
