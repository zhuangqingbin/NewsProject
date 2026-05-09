from quote_watcher.alerts.indicator import (
    MACDResult,
    cross_above,
    cross_below,
    highest_n_days,
    lowest_n_days,
    ma,
    macd,
    rsi,
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


def test_rsi_returns_none_when_insufficient():
    assert rsi([1.0, 2.0, 3.0], 14) is None
    assert rsi([], 14) is None


def test_rsi_all_gains_returns_100():
    # Strictly increasing series → no losses → RSI saturates at 100
    closes = [float(i) for i in range(20)]   # 0,1,2,...,19
    val = rsi(closes, 14)
    assert val == 100.0


def test_rsi_all_losses_returns_zero():
    closes = [float(20 - i) for i in range(20)]
    val = rsi(closes, 14)
    assert val == 0.0


def test_rsi_known_value():
    """Use a published RSI(14) example. Closes from Wilder's original example
    (Welles Wilder, "New Concepts in Technical Trading Systems"):
    """
    closes = [
        44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
        45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
    ]
    val = rsi(closes, 14)
    # Reference value computed via Wilder smoothing (~57.9)
    assert val is not None
    assert 53.0 < val < 63.0


def test_rsi_overbought_oversold_thresholds():
    """RSI is bounded in [0, 100] for any input."""
    import random
    rng = random.Random(42)
    closes = [100.0 + rng.uniform(-2, 2) for _ in range(50)]
    val = rsi(closes, 14)
    assert val is not None
    assert 0.0 <= val <= 100.0


def test_macd_insufficient_data():
    assert macd([1.0] * 10) is None
    assert macd([], 12, 26, 9) is None


def test_macd_returns_dataclass():
    closes = [100.0 + i * 0.5 for i in range(60)]  # gentle uptrend
    result = macd(closes)
    assert isinstance(result, MACDResult)
    assert result.dif is not None
    assert result.dea is not None
    assert result.hist is not None


def test_macd_uptrend_positive_dif():
    """In a strong uptrend, dif (fast - slow) should be positive."""
    closes = [100.0 + i * 1.0 for i in range(60)]
    result = macd(closes)
    assert result is not None
    assert result.dif > 0


def test_macd_downtrend_negative_dif():
    closes = [100.0 - i * 1.0 for i in range(60)]
    result = macd(closes)
    assert result is not None
    assert result.dif < 0


def test_macd_hist_is_2x_dif_minus_dea():
    closes = [100.0 + i * 0.5 for i in range(60)]
    result = macd(closes)
    assert result is not None
    assert abs(result.hist - 2 * (result.dif - result.dea)) < 1e-9


def test_macd_custom_periods():
    closes = [100.0 + i * 0.3 for i in range(50)]
    r1 = macd(closes, fast=5, slow=10, signal=3)
    r2 = macd(closes, fast=12, slow=26, signal=9)
    assert r1 is not None
    assert r2 is not None
