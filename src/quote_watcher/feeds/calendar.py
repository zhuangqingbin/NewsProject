"""A-share market calendar: trading hours + holidays."""
from __future__ import annotations

from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

import chinese_calendar

BJ = ZoneInfo("Asia/Shanghai")
MORNING_OPEN = time(9, 30)
MORNING_CLOSE = time(11, 30)
AFTERNOON_OPEN = time(13, 0)
AFTERNOON_CLOSE = time(15, 0)

Session = Literal["pre", "morning", "noon_break", "afternoon", "post", "closed"]


class MarketCalendar:
    """A-share trading calendar (timezone-aware)."""

    def is_open(self, dt: datetime) -> bool:
        return self.session(dt) in ("morning", "afternoon")

    def session(self, dt: datetime) -> Session:
        if dt.tzinfo is None:
            raise ValueError("dt must be timezone-aware")
        bj = dt.astimezone(BJ)
        date = bj.date()
        if date.weekday() >= 5 or chinese_calendar.is_holiday(date):
            return "closed"
        t = bj.time()
        if t < MORNING_OPEN:
            return "pre"
        if t < MORNING_CLOSE:
            return "morning"
        if t < AFTERNOON_OPEN:
            return "noon_break"
        if t < AFTERNOON_CLOSE:
            return "afternoon"
        return "post"
