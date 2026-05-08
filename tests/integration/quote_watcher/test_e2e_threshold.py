"""S2 acceptance: fake Sina HQ → SinaFeed → AlertEngine → mock dispatcher.

Verifies the full chain works without hitting network or real Feishu.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.feeds.sina import SinaFeed
from quote_watcher.scheduler.jobs import evaluate_alerts
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase

BJ = ZoneInfo("Asia/Shanghai")

# Sina response: prev_close=100, current=96.93 → -3.07%
SINA_DROP = (
    'var hq_str_sh600519="贵州茅台,100.000,100.000,96.930,'
    '100.000,96.000,96.930,96.940,2823100,5043500000.00,'
    '200,96.930,500,96.880,300,96.830,400,96.780,500,96.730,'
    '100,96.940,200,96.950,300,96.960,400,96.970,500,96.980,'
    '2026-05-08,10:00:25,00";\n'
)


@pytest.mark.asyncio
@respx.mock
async def test_e2e_threshold_drop_3pct_pushes():
    respx.get("https://hq.sinajs.cn/list=sh600519").mock(
        return_value=httpx.Response(200, content=SINA_DROP.encode("gbk"))
    )

    feed = SinaFeed()
    calendar = MarketCalendar()

    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    rule = AlertRule(
        id="maotai_drop_3pct", kind=AlertKind.THRESHOLD,
        ticker="600519", name="贵州茅台",
        expr="pct_change_intraday <= -3.0", cooldown_min=30,
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {"feishu_cn": "ok"}

    open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)
    assert calendar.is_open(open_dt)

    snaps = await feed.fetch([("SH", "600519")])
    assert len(snaps) == 1

    pushed = await evaluate_alerts(
        snaps=snaps, engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert pushed == 1
    msg = dispatcher.dispatch.call_args.args[0]
    assert msg.kind == "alert"
    assert "贵州茅台" in msg.title
    assert "600519" in msg.title


@pytest.mark.asyncio
@respx.mock
async def test_e2e_no_trigger_when_drop_under_threshold():
    """1.5% drop should NOT trigger 3% rule."""
    no_drop_payload = SINA_DROP.replace("96.930", "98.500")  # only -1.5%
    respx.get("https://hq.sinajs.cn/list=sh600519").mock(
        return_value=httpx.Response(200, content=no_drop_payload.encode("gbk"))
    )

    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    engine = AlertEngine(
        rules=[AlertRule(
            id="r1", kind=AlertKind.THRESHOLD,
            ticker="600519", expr="pct_change_intraday <= -3.0",
        )],
        tracker=tracker,
    )
    dispatcher = AsyncMock()
    feed = SinaFeed()
    snaps = await feed.fetch([("SH", "600519")])
    pushed = await evaluate_alerts(
        snaps=snaps, engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert pushed == 0
    dispatcher.dispatch.assert_not_called()


@pytest.mark.asyncio
@respx.mock
async def test_e2e_cooldown_silences_repeat_within_window():
    """Two consecutive ticks with same drop → only ONE push (second silenced by cooldown)."""
    respx.get("https://hq.sinajs.cn/list=sh600519").mock(
        return_value=httpx.Response(200, content=SINA_DROP.encode("gbk"))
    )

    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    times = iter([1000, 1500])
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: next(times))
    rule = AlertRule(
        id="r1", kind=AlertKind.THRESHOLD,
        ticker="600519", expr="pct_change_intraday <= -3.0", cooldown_min=30,
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {}
    feed = SinaFeed()

    # Tick 1
    snaps = await feed.fetch([("SH", "600519")])
    n1 = await evaluate_alerts(
        snaps=snaps, engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    # Tick 2 — within cooldown window
    snaps = await feed.fetch([("SH", "600519")])
    n2 = await evaluate_alerts(
        snaps=snaps, engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert n1 == 1
    assert n2 == 0   # silenced
    assert dispatcher.dispatch.await_count == 1
