# src/news_pipeline/common/timeutil.py
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from news_pipeline.common.enums import Market

_TZ_BY_MARKET: dict[Market, ZoneInfo] = {
    Market.US: ZoneInfo("America/New_York"),
    Market.CN: ZoneInfo("Asia/Shanghai"),
}


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def ensure_utc(t: datetime) -> datetime:
    if t.tzinfo is None:
        return t.replace(tzinfo=UTC)
    return t.astimezone(UTC)


def to_market_local(t: datetime, market: Market) -> datetime:
    return ensure_utc(t).astimezone(_TZ_BY_MARKET[market])


def is_market_hours(t: datetime, market: Market) -> bool:
    local = to_market_local(t, market)
    if local.weekday() >= 5:
        return False
    h, m = local.hour, local.minute
    if market == Market.US:
        # ET 09:30-16:00
        start, end = time(9, 30), time(16, 0)
        return start <= time(h, m) <= end
    if market == Market.CN:
        # CST 09:30-11:30 + 13:00-15:00
        morning = time(9, 30) <= time(h, m) <= time(11, 30)
        afternoon = time(13, 0) <= time(h, m) <= time(15, 0)
        return morning or afternoon
    return False
