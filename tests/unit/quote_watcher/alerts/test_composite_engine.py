# tests/unit/quote_watcher/alerts/test_composite_engine.py
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from news_pipeline.config.schema import HoldingEntry, HoldingsFile, PortfolioCfg
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


def _snap(ticker: str, price: float, prev: float = 1850.0) -> QuoteSnapshot:
    return QuoteSnapshot(
        ticker=ticker, market="SH", name="贵州茅台",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=price, open=prev, high=max(price, prev), low=min(price, prev),
        prev_close=prev, volume=100, amount=1.0, bid1=price, ask1=price + 0.01,
    )


@pytest.mark.asyncio
async def test_composite_holding_triggers_on_loss(tracker: StateTracker):
    holdings = HoldingsFile(holdings=[
        HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0),
    ])
    rule = AlertRule(
        id="maotai_pos_alert", kind=AlertKind.COMPOSITE,
        holding="600519", expr="pct_change_from_cost <= -8.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, holdings=holdings)
    snap = _snap("600519", price=1700.0)  # -8.1% from cost
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert len(verdicts) == 1
    assert verdicts[0].rule.id == "maotai_pos_alert"


@pytest.mark.asyncio
async def test_composite_holding_no_trigger_when_above_threshold(tracker: StateTracker):
    holdings = HoldingsFile(holdings=[
        HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0),
    ])
    rule = AlertRule(
        id="r1", kind=AlertKind.COMPOSITE,
        holding="600519", expr="pct_change_from_cost <= -8.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, holdings=holdings)
    snap = _snap("600519", price=1800.0)  # only -2.7%
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert verdicts == []


@pytest.mark.asyncio
async def test_composite_holding_skipped_when_holding_missing(tracker: StateTracker):
    """Rule references holding=XXX but holdings.yml doesn't have that ticker."""
    holdings = HoldingsFile(holdings=[
        HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0),
    ])
    rule = AlertRule(
        id="r1", kind=AlertKind.COMPOSITE,
        holding="000001", expr="pct_change_from_cost <= -8.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, holdings=holdings)
    snap = _snap("000001", price=10.0, prev=11.0)
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert verdicts == []  # rule skipped because no matching holding


@pytest.mark.asyncio
async def test_composite_holding_combined_expr(tracker: StateTracker):
    """Composite rule combining cost-pnl + intraday volume — both must hit."""
    holdings = HoldingsFile(holdings=[
        HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0),
    ])
    rule = AlertRule(
        id="r1", kind=AlertKind.COMPOSITE,
        holding="600519",
        expr="pct_change_from_cost <= -8.0 and volume_ratio >= 1.5",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, holdings=holdings)
    snap = _snap("600519", price=1700.0)  # -8.1% from cost
    # without volume_avg5d, volume_ratio = 0 → condition fails
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert verdicts == []
    # with volume_avg5d ≤ snap.volume / 1.5 → condition passes
    verdicts = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    assert len(verdicts) == 1


@pytest.mark.asyncio
async def test_portfolio_rule_triggers(tracker: StateTracker):
    holdings = HoldingsFile(
        holdings=[HoldingEntry(ticker="600519", qty=100, cost_per_share=1000.0)],
        portfolio=PortfolioCfg(total_capital=100000),
    )
    rule = AlertRule(
        id="port_pnl_alert", kind=AlertKind.COMPOSITE,
        portfolio=True, expr="total_unrealized_pnl_pct <= -3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, holdings=holdings)
    snap = _snap("600519", price=950.0, prev=1000.0)  # -5% from cost → -5000 pnl → -5%
    verdicts = await engine.evaluate_portfolio(snaps_by_ticker={"600519": snap})
    assert len(verdicts) == 1


@pytest.mark.asyncio
async def test_portfolio_rule_no_trigger(tracker: StateTracker):
    holdings = HoldingsFile(
        holdings=[HoldingEntry(ticker="600519", qty=100, cost_per_share=1000.0)],
        portfolio=PortfolioCfg(total_capital=100000),
    )
    rule = AlertRule(
        id="r1", kind=AlertKind.COMPOSITE,
        portfolio=True, expr="total_unrealized_pnl_pct <= -3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, holdings=holdings)
    snap = _snap("600519", price=990.0, prev=1000.0)  # only -1%
    verdicts = await engine.evaluate_portfolio(snaps_by_ticker={"600519": snap})
    assert verdicts == []


@pytest.mark.asyncio
async def test_portfolio_empty_snapshots(tracker: StateTracker):
    holdings = HoldingsFile(
        holdings=[HoldingEntry(ticker="600519", qty=100, cost_per_share=1000.0)],
        portfolio=PortfolioCfg(total_capital=100000),
    )
    rule = AlertRule(
        id="r1", kind=AlertKind.COMPOSITE,
        portfolio=True, expr="total_unrealized_pnl_pct <= -3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, holdings=holdings)
    verdicts = await engine.evaluate_portfolio(snaps_by_ticker={})
    assert verdicts == []


@pytest.mark.asyncio
async def test_threshold_rules_still_work(tracker: StateTracker):
    """Regression: existing threshold rules unaffected by composite changes."""
    rule = AlertRule(
        id="r1", kind=AlertKind.THRESHOLD,
        ticker="600519", expr="pct_change_intraday <= -3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)  # no holdings arg
    snap = _snap("600519", price=96.5, prev=100.0)
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert len(verdicts) == 1
