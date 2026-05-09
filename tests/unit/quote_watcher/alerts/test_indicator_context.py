# tests/unit/quote_watcher/alerts/test_indicator_context.py
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from quote_watcher.alerts.context import build_indicator_context
from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.store.kline import DailyBar

BJ = ZoneInfo("Asia/Shanghai")


def _bar(d: date, close: float) -> DailyBar:
    return DailyBar(
        ticker="600519", trade_date=d,
        open=close, high=close, low=close, close=close, prev_close=close,
        volume=1000, amount=10000.0,
    )


def make_snap(price: float) -> QuoteSnapshot:
    return QuoteSnapshot(
        ticker="600519", market="SH", name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=price, open=price, high=price, low=price,
        prev_close=price, volume=100, amount=1.0, bid1=price, ask1=price,
    )


def test_indicator_ctx_inherits_threshold_keys():
    snap = make_snap(100.0)
    bars = [_bar(date(2026, 4, 1), 100.0)]
    ctx = build_indicator_context(snap, bars=bars, volume_avg5d=50)
    assert "price_now" in ctx
    assert "pct_change_intraday" in ctx
    assert "volume_ratio" in ctx
    assert "is_limit_up" in ctx


def test_indicator_ctx_ma_today_uses_price_now():
    """ma5 uses last 4 closes + today's price."""
    snap = make_snap(110.0)
    # 4 prior closes all = 100; ma5_today = (100*4 + 110) / 5 = 102
    bars = [_bar(date(2026, 5, i + 1), 100.0) for i in range(4)]
    ctx = build_indicator_context(snap, bars=bars, volume_avg5d=50)
    assert ctx["ma5"] == 102.0
    # ma5_yday uses prior 5 closes — only 4 available → None
    assert ctx["ma5_yday"] is None


def test_indicator_ctx_ma_with_enough_history():
    snap = make_snap(110.0)
    # 6 prior closes = [100,100,100,100,100,100]
    bars = [_bar(date(2026, 5, i + 1), 100.0) for i in range(6)]
    ctx = build_indicator_context(snap, bars=bars, volume_avg5d=50)
    # ma5_today = (100*4 + 110) / 5 = 102
    assert ctx["ma5"] == 102.0
    # ma5_yday = mean of last 5 prior bars = 100.0
    assert ctx["ma5_yday"] == 100.0


def test_indicator_ctx_cross_above_callable():
    snap = make_snap(110.0)
    bars = [_bar(date(2026, 5, i + 1), 100.0) for i in range(6)]
    ctx = build_indicator_context(snap, bars=bars, volume_avg5d=50)
    # cross_above(ma5, ma20) — today_a=102 <= today_b=105 → False (no yday supplied → strict gt)
    assert ctx["cross_above"](ctx["ma5"], 105.0) is False
    # cross_above with yday: today_a=102>100 AND yday_a=99<=100 → True (genuine cross)
    assert ctx["cross_above"](102.0, 100.0, yday_a=99.0, yday_b=100.0) is True
    # yday_a=101 > yday_b=100 already above — not a fresh cross → False
    assert ctx["cross_above"](102.0, 100.0, yday_a=101.0, yday_b=100.0) is False


def test_indicator_ctx_rsi_callable():
    snap = make_snap(120.0)
    # 20 prior closes ascending → all gains → ma5_yday=mean of last 5 prior
    bars = [_bar(date(2026, 5, i + 1), float(100 + i)) for i in range(20)]
    ctx = build_indicator_context(snap, bars=bars, volume_avg5d=50)
    # rsi callable should work with default n=14
    val = ctx["rsi"](14)
    assert val is not None
    assert 0 <= val <= 100


def test_indicator_ctx_macd_precomputed():
    snap = make_snap(120.0)
    base_date = date(2026, 1, 1)
    bars = [_bar(base_date + timedelta(days=i), float(100 + i * 0.5)) for i in range(60)]
    ctx = build_indicator_context(snap, bars=bars, volume_avg5d=50)
    # macd_* keys exist; values may be 0 or non-None
    assert "macd_dif" in ctx
    assert "macd_dea" in ctx
    assert "macd_hist" in ctx
    # In an uptrend dif > 0
    assert ctx["macd_dif"] > 0


def test_indicator_ctx_highest_lowest_callables():
    snap = make_snap(120.0)
    bars = [_bar(date(2026, 5, i + 1), 100.0 + i) for i in range(20)]
    ctx = build_indicator_context(snap, bars=bars, volume_avg5d=50)
    # closes_today = prior + price_now → last 5: [115, 116, 117, 118, 119, 120]
    assert ctx["highest_n_days"](5) == 120.0
    assert ctx["lowest_n_days"](5) == 116.0


def test_indicator_ctx_empty_bars():
    snap = make_snap(100.0)
    ctx = build_indicator_context(snap, bars=[], volume_avg5d=50)
    assert ctx["ma5"] is None
    assert ctx["ma5_yday"] is None
    assert ctx["macd_dif"] == 0.0  # default 0 when not enough data
    assert ctx["macd_dea"] == 0.0
    assert ctx["macd_hist"] == 0.0
    assert ctx["rsi"](14) is None
