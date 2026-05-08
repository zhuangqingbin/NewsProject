"""Quote watcher scheduler jobs."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from quote_watcher.feeds.base import QuoteFeed
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.store.tick import TickRing
from shared.observability.log import get_logger

BJ = ZoneInfo("Asia/Shanghai")
log = get_logger(__name__)


async def poll_quotes(
    *,
    feed: QuoteFeed,
    calendar: MarketCalendar,
    ring: TickRing,
    tickers: list[tuple[str, str]],
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(BJ)
    if not calendar.is_open(now):
        return 0
    snaps = await feed.fetch(tickers)
    for s in snaps:
        ring.append(s)
    if snaps:
        log.info("poll_quotes_ok", count=len(snaps))
    return len(snaps)
