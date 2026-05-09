"""Technical indicators for quote_watcher AlertEngine.

Pure functions — no I/O. Used by `build_indicator_context` to inject into
asteval as both pre-computed values (e.g. ma5) and callables (e.g. cross_above).
"""
from __future__ import annotations


def ma(closes: list[float], n: int) -> float | None:
    """Simple moving average over last `n` closes."""
    if n <= 0 or len(closes) < n:
        return None
    last_n = closes[-n:]
    return sum(last_n) / n


def cross_above(
    today_a: float, today_b: float, yday_a: float, yday_b: float,
) -> bool:
    """True iff `a` crossed above `b` between yesterday and today."""
    return today_a > today_b and yday_a <= yday_b


def cross_below(
    today_a: float, today_b: float, yday_a: float, yday_b: float,
) -> bool:
    """True iff `a` crossed below `b` between yesterday and today."""
    return today_a < today_b and yday_a >= yday_b


def highest_n_days(closes: list[float], n: int) -> float | None:
    if n <= 0 or len(closes) < n:
        return None
    return max(closes[-n:])


def lowest_n_days(closes: list[float], n: int) -> float | None:
    if n <= 0 or len(closes) < n:
        return None
    return min(closes[-n:])


def rsi(closes: list[float], n: int = 14) -> float | None:
    """Wilder's RSI(n). Returns None if not enough data."""
    if n <= 0 or len(closes) < n + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    # Initial average over first n diffs
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    # Wilder smoothing for the rest
    for i in range(n, len(gains)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)
