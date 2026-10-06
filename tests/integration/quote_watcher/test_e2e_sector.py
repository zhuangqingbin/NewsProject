"""S6 acceptance: fake Eastmoney 板块 → SectorFeed → AlertEngine → mock dispatcher."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import respx

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.feeds.sector import SectorFeed
from quote_watcher.scheduler.jobs import evaluate_sector_alerts
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase

BJ = ZoneInfo("Asia/Shanghai")


@pytest.mark.asyncio
async def test_e2e_sector_surge_pushes(quote_db: QuoteDatabase):
    df = pd.DataFrame(
        [
            {"板块名称": "半导体", "涨跌幅": 3.5, "换手率": 5.2},
            {"板块名称": "新能源", "涨跌幅": -1.0, "换手率": 2.0},
        ]
    )
    tracker = StateTracker(dao=AlertStateDAO(quote_db), now_fn=lambda: 1000)
    rule = AlertRule(
        id="semi_surge",
        kind=AlertKind.EVENT,
        target_kind="sector",
        sector="半导体",
        expr="sector_pct_change >= 3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    cal = MarketCalendar()
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {}

    open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)
    with respx.mock() as mock:
        rows = [
            {"f14": r["板块名称"], "f3": r["涨跌幅"], "f8": r["换手率"], "f10": "-"}
            for r in df.to_dict("records")
        ]
        mock.get("https://push2.eastmoney.com/api/qt/clist/get").respond(
            200, json={"data": {"diff": rows, "total": len(rows)}}
        )
        feed = SectorFeed()
        n = await evaluate_sector_alerts(
            feed=feed,
            engine=engine,
            calendar=cal,
            dispatcher=dispatcher,
            channels=["feishu_cn"],
            now=open_dt,
        )
    assert n == 1
    msg = dispatcher.dispatch.call_args.args[0]
    assert msg.kind == "alert"


@pytest.mark.asyncio
async def test_e2e_sector_no_trigger_when_calm(quote_db: QuoteDatabase):
    df = pd.DataFrame(
        [
            {"板块名称": "半导体", "涨跌幅": 1.0, "换手率": 5.2},
            {"板块名称": "新能源", "涨跌幅": -0.5, "换手率": 2.0},
        ]
    )
    tracker = StateTracker(dao=AlertStateDAO(quote_db), now_fn=lambda: 1000)
    rule = AlertRule(
        id="r1",
        kind=AlertKind.EVENT,
        target_kind="sector",
        sector="半导体",
        expr="sector_pct_change >= 3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    cal = MarketCalendar()
    dispatcher = AsyncMock()
    open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)
    with respx.mock() as mock:
        rows = [
            {"f14": r["板块名称"], "f3": r["涨跌幅"], "f8": r["换手率"], "f10": "-"}
            for r in df.to_dict("records")
        ]
        mock.get("https://push2.eastmoney.com/api/qt/clist/get").respond(
            200, json={"data": {"diff": rows, "total": len(rows)}}
        )
        feed = SectorFeed()
        n = await evaluate_sector_alerts(
            feed=feed,
            engine=engine,
            calendar=cal,
            dispatcher=dispatcher,
            channels=["feishu_cn"],
            now=open_dt,
        )
    assert n == 0
    dispatcher.dispatch.assert_not_called()
