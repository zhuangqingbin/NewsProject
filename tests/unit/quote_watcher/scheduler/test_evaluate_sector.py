# tests/unit/quote_watcher/scheduler/test_evaluate_sector.py
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.feeds.sector import SectorSnapshot
from quote_watcher.scheduler.jobs import evaluate_sector_alerts
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase

BJ = ZoneInfo("Asia/Shanghai")


@pytest.mark.asyncio
async def test_sector_alerts_dispatches_when_triggered():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    rule = AlertRule(
        id="semi_surge", kind=AlertKind.EVENT,
        target_kind="sector", sector="半导体",
        expr="sector_pct_change >= 3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    feed = AsyncMock()
    feed.fetch_pct_changes.return_value = {
        "半导体": SectorSnapshot(name="半导体", pct_change=3.5),
    }
    cal = MarketCalendar()
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {}

    open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)
    n = await evaluate_sector_alerts(
        feed=feed, engine=engine, calendar=cal,
        dispatcher=dispatcher, channels=["feishu_cn"], now=open_dt,
    )
    assert n == 1
    feed.fetch_pct_changes.assert_awaited_once()
    msg = dispatcher.dispatch.call_args.args[0]
    assert msg.kind == "alert"


@pytest.mark.asyncio
async def test_sector_alerts_skips_when_market_closed():
    feed = AsyncMock()
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    engine = AlertEngine(rules=[], tracker=tracker)
    cal = MarketCalendar()
    dispatcher = AsyncMock()

    closed = datetime(2026, 5, 9, 10, 0, tzinfo=BJ)  # Saturday
    n = await evaluate_sector_alerts(
        feed=feed, engine=engine, calendar=cal,
        dispatcher=dispatcher, channels=["feishu_cn"], now=closed,
    )
    assert n == 0
    feed.fetch_pct_changes.assert_not_called()


@pytest.mark.asyncio
async def test_sector_alerts_no_trigger_no_dispatch():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    rule = AlertRule(
        id="r1", kind=AlertKind.EVENT,
        target_kind="sector", sector="半导体",
        expr="sector_pct_change >= 3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    feed = AsyncMock()
    feed.fetch_pct_changes.return_value = {
        "半导体": SectorSnapshot(name="半导体", pct_change=1.0),  # below 3
    }
    cal = MarketCalendar()
    dispatcher = AsyncMock()

    open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)
    n = await evaluate_sector_alerts(
        feed=feed, engine=engine, calendar=cal,
        dispatcher=dispatcher, channels=["feishu_cn"], now=open_dt,
    )
    assert n == 0
    dispatcher.dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_sector_alerts_no_channels_no_op():
    feed = AsyncMock()
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    engine = AlertEngine(rules=[], tracker=tracker)
    cal = MarketCalendar()
    dispatcher = AsyncMock()
    open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)
    n = await evaluate_sector_alerts(
        feed=feed, engine=engine, calendar=cal,
        dispatcher=dispatcher, channels=[], now=open_dt,
    )
    assert n == 0
    feed.fetch_pct_changes.assert_not_called()
