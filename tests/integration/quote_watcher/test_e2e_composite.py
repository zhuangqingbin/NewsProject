"""S3 acceptance: holdings.yml + composite rule end-to-end.

SinaFeed → AlertEngine → mock dispatcher.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from news_pipeline.config.schema import HoldingEntry, HoldingsFile, PortfolioCfg
from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.emit.message import build_alert_message
from quote_watcher.feeds.sina import SinaFeed
from quote_watcher.scheduler.jobs import evaluate_alerts
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase

# Maotai @ 1700, prev_close 1850 (-8.1% intraday).
# If cost was 1850 then pct_change_from_cost is also -8.1%.
SINA_AT_LOSS = (
    'var hq_str_sh600519="贵州茅台,1850.000,1850.000,1700.000,'
    '1850.000,1700.000,1700.000,1700.010,2823100,5043500000.00,'
    '200,1700.000,500,1699.500,300,1699.000,400,1698.500,500,1698.000,'
    '100,1700.010,200,1700.020,300,1700.030,400,1700.040,500,1700.050,'
    '2026-05-08,10:00:25,00";\n'
)


@pytest.mark.asyncio
@respx.mock
async def test_e2e_composite_holding_loss_pushes():
    respx.get("https://hq.sinajs.cn/list=sh600519").mock(
        return_value=httpx.Response(200, content=SINA_AT_LOSS.encode("gbk"))
    )

    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    holdings = HoldingsFile(
        holdings=[HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0)],
        portfolio=PortfolioCfg(total_capital=200000),
    )
    rule = AlertRule(
        id="maotai_pos_alert", kind=AlertKind.COMPOSITE,
        holding="600519", expr="pct_change_from_cost <= -8.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, holdings=holdings)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {"feishu_cn": "ok"}

    feed = SinaFeed()
    snaps = await feed.fetch([("SH", "600519")])
    pushed = await evaluate_alerts(
        snaps=snaps, engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert pushed == 1
    msg = dispatcher.dispatch.call_args.args[0]
    assert "贵州茅台" in msg.title
    assert msg.kind == "alert"


@pytest.mark.asyncio
@respx.mock
async def test_e2e_portfolio_total_loss_pushes():
    respx.get("https://hq.sinajs.cn/list=sh600519").mock(
        return_value=httpx.Response(200, content=SINA_AT_LOSS.encode("gbk"))
    )

    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    # 600519 cost 1850 x 100 shares = 185000 capital invested
    # current 1700 -> -150 x 100 = -15000 PnL
    # total_capital 200000 -> pnl_pct = -15000/200000 = -7.5%
    holdings = HoldingsFile(
        holdings=[HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0)],
        portfolio=PortfolioCfg(total_capital=200000),
    )
    rule = AlertRule(
        id="port_alert", kind=AlertKind.COMPOSITE,
        portfolio=True, expr="total_unrealized_pnl_pct <= -3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, holdings=holdings)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {"feishu_cn": "ok"}

    feed = SinaFeed()
    snaps = await feed.fetch([("SH", "600519")])
    snaps_by_ticker = {s.ticker: s for s in snaps}
    verdicts = await engine.evaluate_portfolio(snaps_by_ticker=snaps_by_ticker)
    assert len(verdicts) == 1

    # Simulate what main.py does for portfolio verdicts
    for v in verdicts:
        msg = build_alert_message(v)
        await dispatcher.dispatch(msg, channels=["feishu_cn"])

    assert dispatcher.dispatch.await_count == 1
