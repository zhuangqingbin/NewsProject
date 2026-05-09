"""S5 acceptance: synthetic K-line history → INDICATOR rule cross_above triggers → mock dispatcher.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
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
from quote_watcher.store.kline import DailyBar

BJ = ZoneInfo("Asia/Shanghai")


def _bar(d: date, close: float) -> DailyBar:
    return DailyBar(
        ticker="600519", trade_date=d,
        open=close, high=close, low=close, close=close, prev_close=close,
        volume=1000, amount=10000.0,
    )


def _snap(price: float) -> QuoteSnapshot:
    return QuoteSnapshot(
        ticker="600519", market="SH", name="贵州茅台",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=price, open=price, high=price, low=price,
        prev_close=price, volume=100, amount=1.0, bid1=price, ask1=price,
    )


@pytest.mark.asyncio
async def test_e2e_indicator_ma_above():
    """30 days of flat 100 + price spike to 200 today.
    ma5_today = (100*4 + 200)/5 = 120, ma20_today = (100*19 + 200)/20 = 105
    → ma5 > ma20 fires."""
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)

    bars = [_bar(date(2026, 1, 1) + timedelta(days=i), 100.0) for i in range(30)]
    cache = AsyncMock()
    cache.get_cached.return_value = bars

    rule = AlertRule(
        id="maotai_ma_breakout", kind=AlertKind.INDICATOR,
        ticker="600519", expr="ma5 > ma20",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, kline_cache=cache)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {"feishu_cn": "ok"}

    snap = _snap(200.0)
    pushed = await evaluate_alerts(
        snaps=[snap], engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert pushed == 1
    msg = dispatcher.dispatch.call_args.args[0]
    assert msg.kind == "alert"


@pytest.mark.asyncio
async def test_e2e_indicator_no_trigger_in_flat_market():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)

    bars = [_bar(date(2026, 1, 1) + timedelta(days=i), 100.0) for i in range(30)]
    cache = AsyncMock()
    cache.get_cached.return_value = bars

    rule = AlertRule(
        id="r1", kind=AlertKind.INDICATOR,
        ticker="600519", expr="ma5 > ma20",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, kline_cache=cache)
    dispatcher = AsyncMock()

    snap = _snap(100.0)  # flat — ma5 == ma20 → no trigger
    pushed = await evaluate_alerts(
        snaps=[snap], engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert pushed == 0
    dispatcher.dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_e2e_indicator_rsi_oversold():
    """20 bars dropping → today price drops further → RSI(14) oversold."""
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)

    # Strict downtrend → RSI < 25 quickly
    bars = [
        _bar(date(2026, 1, 1) + timedelta(days=i), 100.0 - i * 0.5)
        for i in range(25)
    ]
    cache = AsyncMock()
    cache.get_cached.return_value = bars

    rule = AlertRule(
        id="oversold", kind=AlertKind.INDICATOR,
        ticker="600519", expr="rsi(14) < 25",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, kline_cache=cache)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {"feishu_cn": "ok"}

    snap = _snap(85.0)  # below trend
    pushed = await evaluate_alerts(
        snaps=[snap], engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert pushed == 1
