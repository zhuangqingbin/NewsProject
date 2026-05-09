from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase

BJ = ZoneInfo("Asia/Shanghai")


@pytest.fixture
async def tracker() -> StateTracker:
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    return StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)


def _limit_up_snap(ticker: str, prev: float = 100.0) -> QuoteSnapshot:
    """ask1=0 + bid1>0 + price > prev*1.099 → is_limit_up True."""
    return QuoteSnapshot(
        ticker=ticker, market="SH", name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=prev * 1.10, open=prev, high=prev * 1.10, low=prev,
        prev_close=prev, volume=100, amount=1.0,
        bid1=prev * 1.10, ask1=0.0,
    )


@pytest.mark.asyncio
async def test_event_ticker_limit_up_triggers(tracker: StateTracker):
    rule = AlertRule(
        id="cambricon_limit_up", kind=AlertKind.EVENT,
        target_kind="ticker", ticker="688256",
        expr="is_limit_up",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = _limit_up_snap("688256")
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert len(verdicts) == 1
    assert verdicts[0].rule.id == "cambricon_limit_up"


@pytest.mark.asyncio
async def test_event_ticker_no_trigger_when_not_limit(tracker: StateTracker):
    rule = AlertRule(
        id="r1", kind=AlertKind.EVENT,
        target_kind="ticker", ticker="688256",
        expr="is_limit_up",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = QuoteSnapshot(
        ticker="688256", market="SH", name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=105.0, open=100, high=105, low=100, prev_close=100,
        volume=100, amount=1.0, bid1=105.0, ask1=105.01,  # ask1 != 0 → no limit
    )
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert verdicts == []


@pytest.mark.asyncio
async def test_event_ticker_filter(tracker: StateTracker):
    rule = AlertRule(
        id="r1", kind=AlertKind.EVENT,
        target_kind="ticker", ticker="000001",
        expr="is_limit_up",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = _limit_up_snap("688256")  # different ticker
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert verdicts == []


@pytest.mark.asyncio
async def test_event_ticker_cooldown(tracker: StateTracker):
    rule = AlertRule(
        id="r1", kind=AlertKind.EVENT,
        target_kind="ticker", ticker="688256",
        expr="is_limit_up", cooldown_min=1440,
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = _limit_up_snap("688256")
    v1 = await engine.evaluate_for_snapshot(snap)
    v2 = await engine.evaluate_for_snapshot(snap)
    assert len(v1) == 1
    assert v2 == []
