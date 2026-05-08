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


def make_snap(ticker: str, price: float, prev: float, volume: int = 100) -> QuoteSnapshot:
    return QuoteSnapshot(
        ticker=ticker, market="SH", name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=price, open=prev, high=max(price, prev), low=min(price, prev),
        prev_close=prev, volume=volume, amount=1.0,
        bid1=price, ask1=price + 0.01,
    )


@pytest.mark.asyncio
async def test_threshold_triggers(tracker: StateTracker):
    rule = AlertRule(
        id="r1", kind=AlertKind.THRESHOLD,
        ticker="600519", expr="pct_change_intraday <= -3.0", cooldown_min=30,
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = make_snap("600519", price=96.5, prev=100.0)  # -3.5%
    verdicts = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    assert len(verdicts) == 1
    assert verdicts[0].rule.id == "r1"


@pytest.mark.asyncio
async def test_threshold_does_not_trigger(tracker: StateTracker):
    rule = AlertRule(
        id="r1", kind=AlertKind.THRESHOLD,
        ticker="600519", expr="pct_change_intraday <= -3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = make_snap("600519", price=98.0, prev=100.0)  # only -2%
    verdicts = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    assert verdicts == []


@pytest.mark.asyncio
async def test_cooldown_silences_repeat(tracker: StateTracker):
    rule = AlertRule(
        id="r1", kind=AlertKind.THRESHOLD,
        ticker="600519", expr="pct_change_intraday <= -3.0", cooldown_min=30,
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = make_snap("600519", price=96.5, prev=100.0)
    v1 = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    v2 = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    assert len(v1) == 1
    assert v2 == []


@pytest.mark.asyncio
async def test_target_filter(tracker: StateTracker):
    rule = AlertRule(
        id="r1", kind=AlertKind.THRESHOLD,
        ticker="000001", expr="pct_change_intraday <= -3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = make_snap("600519", price=96.5, prev=100.0)
    verdicts = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    assert verdicts == []


@pytest.mark.asyncio
async def test_non_threshold_kinds_ignored(tracker: StateTracker):
    """S2.3.4 only handles threshold. Other kinds should not trigger."""
    rule = AlertRule(
        id="r1", kind=AlertKind.INDICATOR,
        ticker="600519", expr="rsi(14) < 25",  # syntactically valid
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = make_snap("600519", price=96.5, prev=100.0)
    verdicts = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    assert verdicts == []  # indicator branch not implemented


@pytest.mark.asyncio
async def test_two_rules_both_trigger(tracker: StateTracker):
    rules = [
        AlertRule(id="r_pct", kind=AlertKind.THRESHOLD,
                  ticker="600519", expr="pct_change_intraday <= -3.0"),
        AlertRule(id="r_vol", kind=AlertKind.THRESHOLD,
                  ticker="600519", expr="volume_today >= 50"),
    ]
    engine = AlertEngine(rules=rules, tracker=tracker)
    snap = make_snap("600519", price=96.5, prev=100.0, volume=100)
    verdicts = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    assert len(verdicts) == 2
    assert {v.rule.id for v in verdicts} == {"r_pct", "r_vol"}


@pytest.mark.asyncio
async def test_eval_error_does_not_crash(tracker: StateTracker):
    """A rule that references an undefined variable should be skipped, not crash."""
    rule = AlertRule(
        id="bad", kind=AlertKind.THRESHOLD,
        ticker="600519", expr="undefined_var > 0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = make_snap("600519", price=100, prev=100)
    verdicts = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    assert verdicts == []
