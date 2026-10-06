from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.alerts.context import build_threshold_context
from quote_watcher.feeds.base import QuoteSnapshot

BJ = ZoneInfo("Asia/Shanghai")


def make_snap(price: float, prev_close: float, volume: int = 100) -> QuoteSnapshot:
    return QuoteSnapshot(
        ticker="600519",
        market="SH",
        name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=price,
        open=prev_close,
        high=price,
        low=prev_close,
        prev_close=prev_close,
        volume=volume,
        amount=1.0,
        bid1=price,
        ask1=price + 0.01,
    )


def test_basic_threshold_ctx():
    snap = make_snap(price=1789.5, prev_close=1845.36)
    ctx = build_threshold_context(snap, volume_avg5d=50)
    assert ctx["price_now"] == 1789.5
    assert ctx["prev_close"] == 1845.36
    assert abs(ctx["pct_change_intraday"] - ((1789.5 - 1845.36) / 1845.36 * 100)) < 1e-6
    assert ctx["volume_today"] == 100
    assert ctx["volume_avg5d"] == 50
    assert ctx["volume_ratio"] == 2.0
    assert ctx["now_hhmm"] == 1000


def test_zero_avg_volume_ratio_zero():
    snap = make_snap(price=10, prev_close=10, volume=100)
    ctx = build_threshold_context(snap, volume_avg5d=0)
    assert ctx["volume_ratio"] == 0.0


def test_limit_up_heuristic():
    # ask1==0 + bid1>0 + price > 1.099*prev_close → limit_up
    snap = QuoteSnapshot(
        ticker="600519",
        market="SH",
        name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=110.0,
        open=100.0,
        high=110.0,
        low=100.0,
        prev_close=100.0,
        volume=100,
        amount=1.0,
        bid1=110.0,
        ask1=0.0,
    )
    ctx = build_threshold_context(snap, volume_avg5d=50)
    assert ctx["is_limit_up"] is True
    assert ctx["is_limit_down"] is False


def test_limit_down_heuristic():
    snap = QuoteSnapshot(
        ticker="600519",
        market="SH",
        name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=90.0,
        open=100.0,
        high=100.0,
        low=90.0,
        prev_close=100.0,
        volume=100,
        amount=1.0,
        bid1=0.0,
        ask1=90.0,
    )
    ctx = build_threshold_context(snap, volume_avg5d=50)
    assert ctx["is_limit_up"] is False
    assert ctx["is_limit_down"] is True


def test_yday_high_low_passthrough():
    snap = make_snap(price=100, prev_close=100)
    ctx = build_threshold_context(
        snap,
        volume_avg5d=50,
        price_high_today_yday=105.0,
        price_low_today_yday=95.0,
    )
    assert ctx["price_high_today_yday"] == 105.0
    assert ctx["price_low_today_yday"] == 95.0


@pytest.mark.parametrize("ratio", [0.0, 1.36])
def test_source_volume_ratio_takes_precedence(ratio):
    snap = replace(make_snap(price=100, prev_close=100), volume_ratio=ratio)
    assert build_threshold_context(snap, volume_avg5d=50)["volume_ratio"] == ratio


@pytest.mark.parametrize(
    ("price", "is_up", "is_down"),
    [(119.995, True, False), (119.99, False, False), (80.005, False, True), (80.01, False, False)],
)
def test_explicit_limit_prices_use_half_cent_tolerance(price, is_up, is_down):
    snap = replace(make_snap(price=price, prev_close=100), limit_up=120.0, limit_down=80.0)
    ctx = build_threshold_context(snap)
    assert ctx["is_limit_up"] is is_up
    assert ctx["is_limit_down"] is is_down


def test_explicit_limit_prices_override_ten_percent_heuristic():
    snap = replace(make_snap(price=110, prev_close=100), ask1=0.0, limit_up=120.0)
    assert build_threshold_context(snap)["is_limit_up"] is False
