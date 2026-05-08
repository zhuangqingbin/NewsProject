"""Context builder for AlertEngine — produces variable map injected into asteval."""
from __future__ import annotations

from typing import Any

from news_pipeline.config.schema import HoldingEntry, HoldingsFile
from quote_watcher.feeds.base import QuoteSnapshot


def build_threshold_context(
    snap: QuoteSnapshot,
    *,
    volume_avg5d: float = 0.0,
    volume_avg20d: float = 0.0,
    price_high_today_yday: float = 0.0,
    price_low_today_yday: float = 0.0,
) -> dict[str, Any]:
    volume_ratio = (snap.volume / volume_avg5d) if volume_avg5d > 0 else 0.0
    is_limit_up = (
        snap.ask1 == 0 and snap.bid1 > 0 and snap.price > snap.prev_close * 1.099
    )
    is_limit_down = (
        snap.bid1 == 0 and snap.ask1 > 0 and snap.price < snap.prev_close * 0.901
    )
    bj = snap.ts
    return {
        "price_now": snap.price,
        "price_open": snap.open,
        "high_today": snap.high,
        "low_today": snap.low,
        "prev_close": snap.prev_close,
        "price_high_today_yday": price_high_today_yday,
        "price_low_today_yday": price_low_today_yday,
        "pct_change_intraday": snap.pct_change,
        "volume_today": snap.volume,
        "amount_today": snap.amount,
        "volume_avg5d": volume_avg5d,
        "volume_avg20d": volume_avg20d,
        "volume_ratio": volume_ratio,
        "bid1": snap.bid1,
        "ask1": snap.ask1,
        "is_limit_up": is_limit_up,
        "is_limit_down": is_limit_down,
        "now_hhmm": bj.hour * 100 + bj.minute,
    }


def build_composite_holding_context(
    snap: QuoteSnapshot,
    holding: HoldingEntry,
    *,
    volume_avg5d: float = 0.0,
    volume_avg20d: float = 0.0,
) -> dict[str, Any]:
    """Composite context for a single holding — threshold context plus cost/qty/pnl."""
    base = build_threshold_context(
        snap, volume_avg5d=volume_avg5d, volume_avg20d=volume_avg20d,
    )
    pct_from_cost = (
        (snap.price - holding.cost_per_share) / holding.cost_per_share * 100
        if holding.cost_per_share > 0
        else 0.0
    )
    pnl = (snap.price - holding.cost_per_share) * holding.qty
    pnl_pct = (
        pnl / (holding.cost_per_share * holding.qty) * 100
        if holding.cost_per_share > 0 and holding.qty > 0
        else 0.0
    )
    base.update({
        "cost_per_share": holding.cost_per_share,
        "qty": holding.qty,
        "pct_change_from_cost": pct_from_cost,
        "unrealized_pnl": pnl,
        "unrealized_pnl_pct": pnl_pct,
    })
    return base


def build_composite_portfolio_context(
    holdings: HoldingsFile,
    snaps_by_ticker: dict[str, QuoteSnapshot],
) -> dict[str, Any]:
    """Aggregate context for portfolio-level composite rules."""
    total_pnl = 0.0
    in_loss = 0
    for h in holdings.holdings:
        snap = snaps_by_ticker.get(h.ticker)
        if snap is None:
            continue
        pnl = (snap.price - h.cost_per_share) * h.qty
        total_pnl += pnl
        if pnl < 0:
            in_loss += 1
    capital = holdings.portfolio.total_capital
    pnl_pct = (total_pnl / capital * 100) if capital and capital > 0 else 0.0
    return {
        "total_unrealized_pnl": total_pnl,
        "total_unrealized_pnl_pct": pnl_pct,
        "holding_count_in_loss": in_loss,
    }
