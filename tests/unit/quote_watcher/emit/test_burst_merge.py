"""Regression: same-ticker multi-rule trigger should produce ONE alert_burst push, not N."""
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


@pytest.mark.asyncio
async def test_two_rules_same_ticker_merged_into_one_alert_burst():
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

    snap = QuoteSnapshot(
        ticker="600519", market="SH", name="贵州茅台",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=96.5, open=100, high=100, low=95, prev_close=100,
        volume=1000, amount=1.0, bid1=96.5, ask1=96.51,
    )
    n = await evaluate_alerts(
        snaps=[snap], engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert n == 1
    assert dispatcher.dispatch.await_count == 1
    msg = dispatcher.dispatch.call_args.args[0]
    assert msg.kind == "alert_burst"


@pytest.mark.asyncio
async def test_three_rules_same_ticker_still_one_burst():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    rules = [
        AlertRule(id=f"r{i}", kind=AlertKind.THRESHOLD, ticker="600519",
                  expr="pct_change_intraday <= -3.0")
        for i in range(3)
    ]
    engine = AlertEngine(rules=rules, tracker=tracker)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {}

    snap = QuoteSnapshot(
        ticker="600519", market="SH", name="贵州茅台",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=96.5, open=100, high=100, low=95, prev_close=100,
        volume=1000, amount=1.0, bid1=96.5, ask1=96.51,
    )
    await evaluate_alerts(
        snaps=[snap], engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert dispatcher.dispatch.await_count == 1


@pytest.mark.asyncio
async def test_two_tickers_each_one_rule_two_dispatches():
    """Different tickers = different messages (no cross-ticker burst)."""
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    rules = [
        AlertRule(id="r_a", kind=AlertKind.THRESHOLD,
                  ticker="600519", expr="pct_change_intraday <= -3.0"),
        AlertRule(id="r_b", kind=AlertKind.THRESHOLD,
                  ticker="000001", expr="pct_change_intraday <= -3.0"),
    ]
    engine = AlertEngine(rules=rules, tracker=tracker)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {}

    snap_a = QuoteSnapshot(
        ticker="600519", market="SH", name="贵州茅台",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=96.5, open=100, high=100, low=95, prev_close=100,
        volume=1000, amount=1.0, bid1=96.5, ask1=96.51,
    )
    snap_b = QuoteSnapshot(
        ticker="000001", market="SZ", name="平安银行",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=12, open=14, high=14, low=12, prev_close=14,
        volume=1000, amount=1.0, bid1=12, ask1=12.01,
    )
    await evaluate_alerts(
        snaps=[snap_a, snap_b], engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert dispatcher.dispatch.await_count == 2
    msgs = [call.args[0] for call in dispatcher.dispatch.call_args_list]
    assert all(m.kind == "alert" for m in msgs)
