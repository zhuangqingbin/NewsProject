from datetime import datetime
from zoneinfo import ZoneInfo

from news_pipeline.config.schema import HoldingEntry, HoldingsFile, PortfolioCfg
from quote_watcher.alerts.context import (
    build_composite_holding_context,
    build_composite_portfolio_context,
)
from quote_watcher.feeds.base import QuoteSnapshot

BJ = ZoneInfo("Asia/Shanghai")


def make_snap(ticker: str, price: float) -> QuoteSnapshot:
    return QuoteSnapshot(
        ticker=ticker, market="SH", name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=price, open=price, high=price, low=price,
        prev_close=price, volume=100, amount=1.0, bid1=price, ask1=price + 0.01,
    )


def test_holding_context_pnl_negative():
    snap = make_snap("600519", 1700.0)
    holding = HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0)
    ctx = build_composite_holding_context(snap, holding, volume_avg5d=50)
    assert ctx["price_now"] == 1700.0
    assert ctx["cost_per_share"] == 1850.0
    assert ctx["qty"] == 100
    assert abs(ctx["pct_change_from_cost"] - ((1700 - 1850) / 1850 * 100)) < 1e-6
    assert ctx["unrealized_pnl"] == (1700 - 1850) * 100
    # unrealized_pnl_pct == pct_change_from_cost (same formula)
    assert abs(ctx["unrealized_pnl_pct"] - ((1700 - 1850) / 1850 * 100)) < 1e-6


def test_holding_context_inherits_threshold_keys():
    """The composite-holding context should ALSO have all threshold keys."""
    snap = make_snap("600519", 100.0)
    holding = HoldingEntry(ticker="600519", qty=100, cost_per_share=100.0)
    ctx = build_composite_holding_context(snap, holding, volume_avg5d=50)
    # threshold-level keys
    assert "price_now" in ctx
    assert "pct_change_intraday" in ctx
    assert "volume_ratio" in ctx
    assert "is_limit_up" in ctx
    # composite-level extras
    assert "cost_per_share" in ctx
    assert "qty" in ctx
    assert "pct_change_from_cost" in ctx


def test_portfolio_context_total_pnl():
    holdings = HoldingsFile(
        holdings=[
            HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0),
            HoldingEntry(ticker="300750", qty=200, cost_per_share=220.0),
        ],
        portfolio=PortfolioCfg(total_capital=200000),
    )
    snaps = {
        "600519": make_snap("600519", 1700.0),  # -150 x 100 = -15000
        "300750": make_snap("300750", 200.0),   # -20 x 200 = -4000
    }
    ctx = build_composite_portfolio_context(holdings, snaps)
    assert ctx["total_unrealized_pnl"] == -15000 + -4000
    assert ctx["total_unrealized_pnl_pct"] == (-19000 / 200000) * 100
    assert ctx["holding_count_in_loss"] == 2


def test_portfolio_context_skips_missing_snaps():
    """If a holding has no current snapshot, skip it (don't crash)."""
    holdings = HoldingsFile(
        holdings=[
            HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0),
            HoldingEntry(ticker="missing", qty=100, cost_per_share=100.0),
        ],
        portfolio=PortfolioCfg(total_capital=200000),
    )
    snaps = {"600519": make_snap("600519", 1700.0)}
    ctx = build_composite_portfolio_context(holdings, snaps)
    # Only 600519 contributes: -15000
    assert ctx["total_unrealized_pnl"] == -15000
    assert ctx["holding_count_in_loss"] == 1


def test_portfolio_context_no_capital_pct_zero():
    """No total_capital → percentage is 0 (avoid div by zero)."""
    holdings = HoldingsFile(
        holdings=[HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0)],
        portfolio=PortfolioCfg(total_capital=None),
    )
    snaps = {"600519": make_snap("600519", 1700.0)}
    ctx = build_composite_portfolio_context(holdings, snaps)
    assert ctx["total_unrealized_pnl"] == -15000
    assert ctx["total_unrealized_pnl_pct"] == 0.0
