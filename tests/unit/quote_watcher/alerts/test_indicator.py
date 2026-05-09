from quote_watcher.alerts.indicator import (
    cross_above,
    cross_below,
    highest_n_days,
    lowest_n_days,
    ma,
)


def test_ma_basic():
    closes = [10.0, 11.0, 12.0, 13.0, 14.0]
    assert ma(closes, 5) == 12.0
    assert ma(closes, 3) == 13.0  # last 3: 12+13+14 / 3
    assert ma(closes, 1) == 14.0


def test_ma_insufficient_data():
    assert ma([1.0, 2.0], 5) is None
    assert ma([], 1) is None


def test_ma_invalid_n():
    assert ma([1.0, 2.0], 0) is None  # 0-period not meaningful
    assert ma([1.0, 2.0], -1) is None


def test_cross_above():
    # MA5 (today=14, yday=11) crosses above MA20 (today=13, yday=12)
    assert cross_above(today_a=14, today_b=13, yday_a=11, yday_b=12) is True
    # No cross — both yday and today MA5 above MA20
    assert cross_above(today_a=14, today_b=13, yday_a=14, yday_b=13) is False
    # No cross — neither today
    assert cross_above(today_a=12, today_b=13, yday_a=11, yday_b=12) is False
    # Edge: yday_a == yday_b (just touching) and today_a > today_b → counts as cross
    assert cross_above(today_a=14, today_b=13, yday_a=12, yday_b=12) is True


def test_cross_below():
    assert cross_below(today_a=12, today_b=13, yday_a=15, yday_b=12) is True
    assert cross_below(today_a=14, today_b=13, yday_a=15, yday_b=12) is False
    # Edge equality
    assert cross_below(today_a=11, today_b=12, yday_a=12, yday_b=12) is True


def test_highest_lowest_basic():
    closes = [10.0, 15.0, 12.0, 8.0, 14.0]
    assert highest_n_days(closes, 5) == 15.0
    assert highest_n_days(closes, 3) == 14.0  # last 3: 12, 8, 14
    assert lowest_n_days(closes, 5) == 8.0
    assert lowest_n_days(closes, 3) == 8.0


def test_highest_lowest_insufficient():
    assert highest_n_days([1.0, 2.0], 5) is None
    assert lowest_n_days([], 1) is None
