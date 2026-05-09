# tests/unit/quote_watcher/scheduler/test_scan_market.py
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from news_pipeline.config.schema import MarketScansCfg
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.feeds.market_scan import MarketRow
from quote_watcher.scheduler.jobs import scan_market

BJ = ZoneInfo("Asia/Shanghai")


def _row(ticker: str, pct: float, vr: float | None = 1.0) -> MarketRow:
    return MarketRow(
        ticker=ticker, name=ticker, market="SH",
        price=10.0, pct_change=pct, volume=1000, amount=1.0,
        volume_ratio=vr,
    )


@pytest.mark.asyncio
async def test_scan_market_skips_when_market_closed():
    feed = AsyncMock()
    feed.fetch.return_value = [_row("A", 9.0)]
    cal = MarketCalendar()
    dispatcher = AsyncMock()
    cfg = MarketScansCfg()

    # Saturday
    closed = datetime(2026, 5, 9, 10, 0, tzinfo=BJ)
    n = await scan_market(
        feed=feed, calendar=cal, dispatcher=dispatcher, channels=["feishu_cn"],
        cfg=cfg, now=closed,
    )
    assert n == 0
    feed.fetch.assert_not_called()
    dispatcher.dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_scan_market_dispatches_when_anomalies():
    feed = AsyncMock()
    feed.fetch.return_value = [_row("A", 9.0, 5.0), _row("B", -8.0, 0.5)]
    cal = MarketCalendar()
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {}
    cfg = MarketScansCfg(push_top_n=5, only_when_score_above=0.0)

    open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)  # Friday open
    n = await scan_market(
        feed=feed, calendar=cal, dispatcher=dispatcher, channels=["feishu_cn"],
        cfg=cfg, now=open_dt,
    )
    assert n == 1
    feed.fetch.assert_awaited_once()
    msg = dispatcher.dispatch.call_args.args[0]
    assert msg.kind == "market_scan"


@pytest.mark.asyncio
async def test_scan_market_no_dispatch_when_all_under_threshold():
    feed = AsyncMock()
    feed.fetch.return_value = [_row("A", 0.5, 1.0), _row("B", -0.5, 0.9)]
    cal = MarketCalendar()
    dispatcher = AsyncMock()
    cfg = MarketScansCfg(push_top_n=5, only_when_score_above=8.0)

    open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)
    n = await scan_market(
        feed=feed, calendar=cal, dispatcher=dispatcher, channels=["feishu_cn"],
        cfg=cfg, now=open_dt,
    )
    assert n == 0
    dispatcher.dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_scan_market_no_channels_no_op():
    feed = AsyncMock()
    feed.fetch.return_value = [_row("A", 9.0)]
    cal = MarketCalendar()
    dispatcher = AsyncMock()
    cfg = MarketScansCfg()
    open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)
    n = await scan_market(
        feed=feed, calendar=cal, dispatcher=dispatcher, channels=[],
        cfg=cfg, now=open_dt,
    )
    assert n == 0
    feed.fetch.assert_not_called()  # short-circuits before fetch
    dispatcher.dispatch.assert_not_called()
