from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.scheduler.jobs import evaluate_alerts
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase

BJ = ZoneInfo("Asia/Shanghai")


def _snap(ticker: str, price: float, prev: float) -> QuoteSnapshot:
    return QuoteSnapshot(
        ticker=ticker, market="SH", name="贵州茅台",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=price, open=prev, high=max(price, prev), low=min(price, prev),
        prev_close=prev, volume=1000, amount=1.0,
        bid1=price, ask1=price + 0.01,
    )


@pytest.mark.asyncio
async def test_evaluate_alerts_dispatches_when_triggered():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    rule = AlertRule(
        id="maotai_drop", kind=AlertKind.THRESHOLD,
        ticker="600519", expr="pct_change_intraday <= -3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {}

    snap = _snap("600519", price=96.5, prev=100.0)  # -3.5%
    n = await evaluate_alerts(
        snaps=[snap], engine=engine, dispatcher=dispatcher,
        channels=["feishu_cn"],
    )
    assert n == 1
    dispatcher.dispatch.assert_awaited_once()
    msg = dispatcher.dispatch.call_args.args[0]
    assert msg.kind == "alert"


@pytest.mark.asyncio
async def test_evaluate_alerts_no_trigger_no_dispatch():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    rule = AlertRule(
        id="r1", kind=AlertKind.THRESHOLD,
        ticker="600519", expr="pct_change_intraday <= -3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    dispatcher = AsyncMock()

    snap = _snap("600519", price=99.5, prev=100.0)  # only -0.5%
    n = await evaluate_alerts(
        snaps=[snap], engine=engine, dispatcher=dispatcher,
        channels=["feishu_cn"],
    )
    assert n == 0
    dispatcher.dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_alerts_burst_merge_for_same_ticker():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    rules = [
        AlertRule(id="r_pct", kind=AlertKind.THRESHOLD,
                  ticker="600519", expr="pct_change_intraday <= -3.0"),
        AlertRule(id="r_vol", kind=AlertKind.THRESHOLD,
                  ticker="600519", expr="volume_today >= 500"),
    ]
    engine = AlertEngine(rules=rules, tracker=tracker)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {}

    snap = _snap("600519", price=96.5, prev=100.0)
    await evaluate_alerts(
        snaps=[snap], engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    # Both rules trigger but ONE merged message (alert_burst)
    assert dispatcher.dispatch.await_count == 1
    msg = dispatcher.dispatch.call_args.args[0]
    assert msg.kind == "alert_burst"
