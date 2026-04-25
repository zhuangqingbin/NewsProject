# tests/unit/common/test_timeutil.py
from datetime import datetime
from zoneinfo import ZoneInfo

from news_pipeline.common.enums import Market
from news_pipeline.common.timeutil import (
    ensure_utc,
    is_market_hours,
    to_market_local,
    utc_now,
)


def test_utc_now_is_aware():
    t = utc_now()
    assert t.tzinfo is not None


def test_ensure_utc_naive_assumed_utc():
    t = ensure_utc(datetime(2026, 4, 25, 12))
    assert str(t.tzinfo) == "UTC"


def test_ensure_utc_converts():
    t = datetime(2026, 4, 25, 12, tzinfo=ZoneInfo("America/New_York"))
    assert ensure_utc(t).hour == 16  # ET 12 = UTC 16 (EDT) or 17 (EST)


def test_us_market_hours():
    t = datetime(2026, 4, 27, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert is_market_hours(t, Market.US)
    closed = datetime(2026, 4, 27, 18, 0, tzinfo=ZoneInfo("America/New_York"))
    assert not is_market_hours(closed, Market.US)
    weekend = datetime(2026, 4, 25, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert not is_market_hours(weekend, Market.US)


def test_cn_market_hours():
    t = datetime(2026, 4, 27, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert is_market_hours(t, Market.CN)
    lunch = datetime(2026, 4, 27, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert not is_market_hours(lunch, Market.CN)


def test_to_market_local():
    t = datetime(2026, 4, 25, 16, 0, tzinfo=ZoneInfo("UTC"))
    local = to_market_local(t, Market.US)
    assert "New_York" in str(local.tzinfo)
