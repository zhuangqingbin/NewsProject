"""Context builder for AlertEngine — produces variable map injected into asteval."""
from __future__ import annotations

from typing import Any

from news_pipeline.config.schema import HoldingEntry, HoldingsFile
from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.feeds.sector import SectorSnapshot


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


def build_indicator_context(
    snap: QuoteSnapshot,
    *,
    bars: list[Any],
    volume_avg5d: float = 0.0,
    volume_avg20d: float = 0.0,
) -> dict[str, Any]:
    """Indicator context = threshold context + MA/RSI/MACD/cross helpers.

    bars: prior daily K bars (sorted asc, NOT including today's intraday bar).
    snap.price is treated as today's close for "today" computations.
    """
    from quote_watcher.alerts import indicator as ind
    from quote_watcher.store.kline import DailyBar  # noqa: F401 — type reference

    base = build_threshold_context(
        snap, volume_avg5d=volume_avg5d, volume_avg20d=volume_avg20d,
    )
    prior_closes: list[float] = [b.close for b in bars]
    closes_today: list[float] = [*prior_closes, snap.price]

    def _ma(n: int) -> float | None:
        return ind.ma(closes_today, n)

    def _ma_yday(n: int) -> float | None:
        return ind.ma(prior_closes, n)

    macd_result = ind.macd(closes_today)
    if macd_result is None:
        macd_dif = macd_dea = macd_hist = 0.0
    else:
        macd_dif = macd_result.dif
        macd_dea = macd_result.dea
        macd_hist = macd_result.hist

    def _rsi(n: int = 14) -> float | None:
        return ind.rsi(closes_today, n)

    def _cross_above(
        today_a: float,
        today_b: float,
        yday_a: float | None = None,
        yday_b: float | None = None,
    ) -> bool:
        # If yday values aren't supplied, the user is comparing scalars only — return strict gt
        if yday_a is None or yday_b is None:
            return today_a > today_b
        return ind.cross_above(today_a, today_b, yday_a, yday_b)

    def _cross_below(
        today_a: float,
        today_b: float,
        yday_a: float | None = None,
        yday_b: float | None = None,
    ) -> bool:
        if yday_a is None or yday_b is None:
            return today_a < today_b
        return ind.cross_below(today_a, today_b, yday_a, yday_b)

    def _highest(n: int) -> float | None:
        return ind.highest_n_days(closes_today, n)

    def _lowest(n: int) -> float | None:
        return ind.lowest_n_days(closes_today, n)

    base.update({
        # Pre-computed MA values (today + yesterday for cross detection convenience)
        "ma5": _ma(5),
        "ma10": _ma(10),
        "ma20": _ma(20),
        "ma60": _ma(60),
        "ma120": _ma(120),
        "ma5_yday": _ma_yday(5),
        "ma10_yday": _ma_yday(10),
        "ma20_yday": _ma_yday(20),
        "ma60_yday": _ma_yday(60),
        "ma120_yday": _ma_yday(120),
        # MACD pre-computed
        "macd_dif": macd_dif,
        "macd_dea": macd_dea,
        "macd_hist": macd_hist,
        # Callables
        "rsi": _rsi,
        "cross_above": _cross_above,
        "cross_below": _cross_below,
        "highest_n_days": _highest,
        "lowest_n_days": _lowest,
    })
    return base


def build_sector_context(sector: str, sector_snap: SectorSnapshot) -> dict[str, Any]:
    """Sector-level context for kind=event + target_kind=sector rules."""
    return {
        "sector_pct_change": sector_snap.pct_change,
        "sector_volume_ratio": (
            sector_snap.volume_ratio if sector_snap.volume_ratio is not None else 0.0
        ),
        "sector_turnover_rate": (
            sector_snap.turnover_rate if sector_snap.turnover_rate is not None else 0.0
        ),
    }
