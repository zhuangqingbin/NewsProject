from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.feeds.calendar import MarketCalendar

BJ = ZoneInfo("Asia/Shanghai")


@pytest.mark.parametrize(
    "dt_str,expected",
    [
        ("2026-05-08 10:00", True),  # Friday morning session
        ("2026-05-08 12:30", False),  # noon break
        ("2026-05-08 14:00", True),  # afternoon session
        ("2026-05-08 16:00", False),  # post-close
        ("2026-05-08 08:00", False),  # pre-open
        ("2026-05-09 10:00", False),  # Saturday
        ("2026-05-10 10:00", False),  # Sunday
        ("2026-05-01 10:00", False),  # Labor Day holiday
    ],
)
def test_is_open(dt_str, expected):
    dt = datetime.fromisoformat(dt_str).replace(tzinfo=BJ)
    cal = MarketCalendar()
    assert cal.is_open(dt) is expected


def test_session_labels():
    cal = MarketCalendar()
    assert cal.session(datetime(2026, 5, 8, 9, 0, tzinfo=BJ)) == "pre"
    assert cal.session(datetime(2026, 5, 8, 10, 0, tzinfo=BJ)) == "morning"
    assert cal.session(datetime(2026, 5, 8, 12, 0, tzinfo=BJ)) == "noon_break"
    assert cal.session(datetime(2026, 5, 8, 14, 0, tzinfo=BJ)) == "afternoon"
    assert cal.session(datetime(2026, 5, 8, 16, 0, tzinfo=BJ)) == "post"
    assert cal.session(datetime(2026, 5, 9, 10, 0, tzinfo=BJ)) == "closed"


def test_naive_datetime_rejected():
    cal = MarketCalendar()
    with pytest.raises(ValueError, match="timezone"):
        cal.is_open(datetime(2026, 5, 8, 10, 0))


@pytest.mark.parametrize(
    "day, previous",
    [
        (date(2026, 10, 8), date(2026, 9, 30)),
        (date(2026, 10, 9), date(2026, 10, 8)),
        (date(2026, 10, 12), date(2026, 10, 9)),
    ],
)
def test_previous_completed_trading_day(day, previous):
    assert MarketCalendar().previous_trading_day(day) == previous
