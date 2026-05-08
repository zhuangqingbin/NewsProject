"""Quote watcher scheduler jobs."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.emit.message import build_alert_message, build_burst_message
from quote_watcher.feeds.base import QuoteFeed, QuoteSnapshot
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.store.tick import TickRing
from shared.observability.log import get_logger
from shared.push.dispatcher import PusherDispatcher

BJ = ZoneInfo("Asia/Shanghai")
log = get_logger(__name__)


async def poll_quotes(
    *,
    feed: QuoteFeed,
    calendar: MarketCalendar,
    ring: TickRing,
    tickers: list[tuple[str, str]],
    now: datetime | None = None,
) -> Sequence[QuoteSnapshot]:
    now = now or datetime.now(BJ)
    if not calendar.is_open(now):
        return []
    snaps = await feed.fetch(tickers)
    for s in snaps:
        ring.append(s)
    if snaps:
        log.info("poll_quotes_ok", count=len(snaps))
    return snaps


async def evaluate_alerts(
    *,
    snaps: Sequence[QuoteSnapshot],
    engine: AlertEngine,
    dispatcher: PusherDispatcher,
    channels: list[str],
) -> int:
    """Evaluate per-snapshot rules; dispatch single or burst message per ticker.

    Returns number of dispatched messages.
    """
    if not channels:
        return 0
    pushed = 0
    for snap in snaps:
        verdicts = await engine.evaluate_for_snapshot(snap)
        if not verdicts:
            continue
        msg = (
            build_alert_message(verdicts[0])
            if len(verdicts) == 1
            else build_burst_message(list(verdicts))
        )
        await dispatcher.dispatch(msg, channels=channels)
        pushed += 1
    return pushed
