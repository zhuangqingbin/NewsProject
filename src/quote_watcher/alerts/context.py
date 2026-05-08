"""Context builder for AlertEngine — produces variable map injected into asteval."""
from __future__ import annotations

from typing import Any

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
