import pytest

from quote_watcher.feeds.sina import parse_sina_response

SAMPLE_SH = (
    'var hq_str_sh600519="贵州茅台,1820.000,1815.500,1789.500,'
    '1825.000,1788.000,1789.500,1789.510,2823100,5043500000.00,'
    '200,1789.500,500,1789.450,300,1789.400,400,1789.350,500,1789.300,'
    '100,1789.510,200,1789.520,300,1789.530,400,1789.540,500,1789.550,'
    '2026-05-08,15:00:25,00";\n'
)
SAMPLE_SZ_SUSPENDED = 'var hq_str_sz000001="";\n'


def test_parse_sina_normal():
    out = parse_sina_response(SAMPLE_SH)
    assert len(out) == 1
    snap = out[0]
    assert snap.ticker == "600519"
    assert snap.market == "SH"
    assert snap.name == "贵州茅台"
    assert snap.open == 1820.0
    assert snap.prev_close == 1815.5
    assert snap.price == 1789.5
    assert snap.high == 1825.0
    assert snap.low == 1788.0
    assert snap.bid1 == 1789.5
    assert snap.ask1 == 1789.51
    assert snap.volume == 2823100
    assert snap.amount == pytest.approx(5043500000.0)
    assert snap.pct_change == pytest.approx((1789.5 - 1815.5) / 1815.5 * 100, rel=1e-6)
    assert snap.ts.year == 2026 and snap.ts.month == 5 and snap.ts.day == 8


def test_parse_sina_suspended_stock_skipped():
    out = parse_sina_response(SAMPLE_SZ_SUSPENDED)
    assert out == []


def test_parse_sina_multi_line():
    payload = SAMPLE_SH + SAMPLE_SZ_SUSPENDED
    out = parse_sina_response(payload)
    assert len(out) == 1
    assert out[0].ticker == "600519"
