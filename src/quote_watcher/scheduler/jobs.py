"""Quote watcher scheduler jobs."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from news_pipeline.config.schema import MarketScansCfg
from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.scan_ranker import rank_market
from quote_watcher.emit.message import build_alert_message, build_burst_message
from quote_watcher.emit.scan_message import build_market_scan_message
from quote_watcher.feeds.base import QuoteFeed, QuoteSnapshot
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.feeds.market_scan import MarketScanFeed
from quote_watcher.feeds.sector import SectorFeed
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


async def scan_market(
    *,
    feed: MarketScanFeed,
    calendar: MarketCalendar,
    dispatcher: PusherDispatcher,
    channels: list[str],
    cfg: MarketScansCfg,
    now: datetime | None = None,
) -> int:
    """Scan A-share spot, dispatch ONE digest message if any anomalies.

    Returns 1 on dispatch, 0 otherwise.
    """
    if not channels:
        return 0
    now_ts = now or datetime.now(BJ)
    if not calendar.is_open(now_ts):
        return 0
    rows = await feed.fetch()
    if not rows:
        return 0
    result = rank_market(rows, cfg)
    if not (result.top_gainers or result.top_losers or result.top_volume_ratio):
        return 0
    msg = build_market_scan_message(result, now=now_ts)
    await dispatcher.dispatch(msg, channels=channels)
    return 1


async def evaluate_sector_alerts(
    *,
    feed: SectorFeed,
    engine: AlertEngine,
    calendar: MarketCalendar,
    dispatcher: PusherDispatcher,
    channels: list[str],
    now: datetime | None = None,
) -> int:
    """Fetch sector data, evaluate sector EVENT rules, dispatch each verdict."""
    if not channels:
        return 0
    now_ts = now or datetime.now(BJ)
    if not calendar.is_open(now_ts):
        return 0
    sector_snaps = await feed.fetch_pct_changes()
    if not sector_snaps:
        return 0
    verdicts = await engine.evaluate_sector(sector_snaps)
    for v in verdicts:
        msg = build_alert_message(v)
        await dispatcher.dispatch(msg, channels=channels)
    return len(verdicts)
