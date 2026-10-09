"""Quote watcher entry point."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from news_pipeline.config.loader import ConfigLoader
from news_pipeline.config.schema import MarketScansCfg
from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.reloader import AlertsReloader
from quote_watcher.emit.message import build_alert_message
from quote_watcher.feeds.base import QuoteFeed
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.feeds.market_scan import MarketScanFeed
from quote_watcher.feeds.sector import SectorFeed
from quote_watcher.feeds.sina import SinaFeed
from quote_watcher.feeds.tencent import TencentFeed
from quote_watcher.health import QuoteFeedHealth
from quote_watcher.scheduler.jobs import (
    evaluate_alerts,
    evaluate_sector_alerts,
    poll_quotes,
    scan_market,
)
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.store.kline import DailyKlineCache
from quote_watcher.store.tick import TickRing
from shared.observability.alert import AlertLevel, BarkAlerter
from shared.observability.heartbeat import Heartbeat
from shared.observability.log import configure_logging, get_logger
from shared.push.dispatcher import PusherDispatcher
from shared.push.factory import build_pushers

BJ = ZoneInfo("Asia/Shanghai")
log = get_logger(__name__)


async def _ticker_poll_loop(
    stop: asyncio.Event,
    interval_sec: float,
    *,
    feed: QuoteFeed,
    calendar: MarketCalendar,
    ring: TickRing,
    tickers: list[tuple[str, str]],
    engine: AlertEngine,
    dispatcher: PusherDispatcher,
    cn_alert_channels: list[str],
    health: QuoteFeedHealth | None = None,
    heartbeat: Heartbeat | None = None,
) -> None:
    while not stop.is_set():
        try:
            snaps = await poll_quotes(
                feed=feed,
                calendar=calendar,
                ring=ring,
                tickers=tickers,
                now=datetime.now(BJ),
            )
            if health is not None:
                await health.observe(bool(snaps), trading=calendar.is_open(datetime.now(BJ)))
            if snaps:
                log.info("quote_feed_ok", source=feed.source_id, count=len(snaps))
                await evaluate_alerts(
                    snaps=snaps,
                    engine=engine,
                    dispatcher=dispatcher,
                    channels=cn_alert_channels,
                )
                snaps_by_ticker = {s.ticker: s for s in snaps}
                portfolio_verdicts = await engine.evaluate_portfolio(
                    snaps_by_ticker=snaps_by_ticker
                )
                for v in portfolio_verdicts:
                    msg = build_alert_message(v)
                    await dispatcher.dispatch(msg, channels=cn_alert_channels)
        except Exception as e:
            log.warning("ticker_loop_failed", error=repr(e))
            if health is not None:
                await health.observe(False, trading=calendar.is_open(datetime.now(BJ)))
        finally:
            if heartbeat is not None:
                heartbeat.complete("poll_quotes")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_sec)


async def _market_scan_loop(
    stop: asyncio.Event,
    interval_sec: float,
    *,
    scan_feed: MarketScanFeed,
    calendar: MarketCalendar,
    dispatcher: PusherDispatcher,
    cn_alert_channels: list[str],
    scan_cfg: MarketScansCfg,
) -> None:
    while not stop.is_set():
        try:
            await scan_market(
                feed=scan_feed,
                calendar=calendar,
                dispatcher=dispatcher,
                channels=cn_alert_channels,
                cfg=scan_cfg,
                now=datetime.now(BJ),
            )
        except Exception as e:
            log.warning("scan_loop_failed", error=str(e))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_sec)


async def _sector_alerts_loop(
    stop: asyncio.Event,
    interval_sec: float,
    *,
    sector_feed: SectorFeed,
    engine: AlertEngine,
    calendar: MarketCalendar,
    dispatcher: PusherDispatcher,
    cn_alert_channels: list[str],
) -> None:
    while not stop.is_set():
        try:
            await evaluate_sector_alerts(
                feed=sector_feed,
                engine=engine,
                calendar=calendar,
                dispatcher=dispatcher,
                channels=cn_alert_channels,
                now=datetime.now(BJ),
            )
        except Exception as e:
            log.warning("sector_loop_failed", error=str(e))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_sec)


async def _amain() -> None:
    cfg_dir = Path(os.environ.get("QUOTE_WATCHER_CONFIG_DIR", "config"))
    db_path = os.environ.get("QUOTE_WATCHER_DB", "data/quotes.db")
    poll_interval_sec = float(os.environ.get("QUOTE_POLL_INTERVAL_SEC", "5"))

    configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"), json_output=True)

    loader = ConfigLoader(cfg_dir)
    snap = loader.load()

    db = QuoteDatabase(f"sqlite+aiosqlite:///{db_path}")
    await db.initialize()

    pushers = build_pushers(snap.channels, snap.secrets)
    dispatcher = PusherDispatcher(pushers)
    cn_alert_channels = [
        c
        for c, ch in snap.channels.channels.items()
        if ch.market == "cn" and ch.enabled and c.endswith("_alert")
    ]

    # === Daily K warmup for indicator rules ===
    kline_cache = DailyKlineCache(db)
    cn_tickers_codes = [e.ticker for e in snap.quote_watchlist.cn]
    if cn_tickers_codes:
        try:
            history = await kline_cache.load_for(cn_tickers_codes, days=250)
            missing = [code for code in cn_tickers_codes if not history.get(code)]
            if missing:
                log.warning("kline_warmup_incomplete", missing=missing)
            else:
                log.info("kline_warmup_ok", tickers=len(cn_tickers_codes))
        except Exception as e:
            log.warning("kline_warmup_failed", error=str(e))

    tracker = StateTracker(dao=AlertStateDAO(db))
    engine = AlertEngine(
        rules=snap.alerts.alerts,
        tracker=tracker,
        holdings=snap.holdings,
        kline_cache=kline_cache,
    )

    reloader = AlertsReloader(
        alerts_path=cfg_dir / "quote_watcher" / "alerts.yml",
        engine=engine,
    )
    reloader.start()

    feed_name = os.environ.get("QUOTE_FEED", "tencent")
    if feed_name not in {"tencent", "sina"}:
        raise ValueError("QUOTE_FEED must be tencent or sina")
    feed: QuoteFeed = TencentFeed() if feed_name == "tencent" else SinaFeed()
    bark_url = snap.secrets.alert.get("bark_url")
    bark = BarkAlerter(bark_url) if bark_url else None
    health = QuoteFeedHealth(bark)
    heartbeat = Heartbeat(
        Path(os.environ.get("HEARTBEAT_PATH", "data/heartbeat_quote_watcher.json"))
    )
    calendar = MarketCalendar()
    ring = TickRing(max_per_ticker=1000)

    tickers: list[tuple[str, str]] = [(e.market, e.ticker) for e in snap.quote_watchlist.cn]

    scan_feed = MarketScanFeed()
    scan_cfg = snap.quote_watchlist.market_scans.get("cn", MarketScansCfg())
    scan_interval_sec = float(os.environ.get("QUOTE_SCAN_INTERVAL_SEC", "60"))

    sector_feed = SectorFeed()
    log.info("quote_scan_providers", market=scan_feed.source_id, sector=sector_feed.source_id)
    sector_interval_sec = float(os.environ.get("QUOTE_SECTOR_INTERVAL_SEC", "60"))

    await _probe_quote_feeds(feed, tickers, scan_feed, sector_feed, bark)
    heartbeat.write()

    log.info(
        "quote_watcher_starting",
        tickers=len(tickers),
        alert_rules=len(snap.alerts.alerts),
        cn_channels=cn_alert_channels,
        poll_sec=poll_interval_sec,
        scan_sec=scan_interval_sec,
        sector_sec=sector_interval_sec,
    )

    stop = asyncio.Event()

    def _on_signal(*_: object) -> None:
        log.info("shutdown_signal")
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _on_signal)

    ticker_task = asyncio.create_task(
        _ticker_poll_loop(
            stop,
            poll_interval_sec,
            feed=feed,
            calendar=calendar,
            ring=ring,
            tickers=tickers,
            engine=engine,
            dispatcher=dispatcher,
            cn_alert_channels=cn_alert_channels,
            health=health,
            heartbeat=heartbeat,
        )
    )
    scan_task = asyncio.create_task(
        _market_scan_loop(
            stop,
            scan_interval_sec,
            scan_feed=scan_feed,
            calendar=calendar,
            dispatcher=dispatcher,
            cn_alert_channels=cn_alert_channels,
            scan_cfg=scan_cfg,
        )
    )
    sector_task = asyncio.create_task(
        _sector_alerts_loop(
            stop,
            sector_interval_sec,
            sector_feed=sector_feed,
            engine=engine,
            calendar=calendar,
            dispatcher=dispatcher,
            cn_alert_channels=cn_alert_channels,
        )
    )

    heartbeat_task = asyncio.create_task(_heartbeat_loop(stop, heartbeat))
    kline_task = asyncio.create_task(_kline_refresh_loop(stop, kline_cache, cn_tickers_codes))
    await stop.wait()
    kline_task.cancel()
    await asyncio.gather(
        ticker_task, scan_task, sector_task, heartbeat_task, kline_task, return_exceptions=True
    )
    reloader.stop()

    await db.close()
    log.info("quote_watcher_stopped")


async def _kline_refresh_loop(
    stop: asyncio.Event, cache: DailyKlineCache, tickers: list[str]
) -> None:
    """Keep completed daily history fresh across trading days without blocking quote polls."""
    while not stop.is_set():
        try:
            await cache.load_for(tickers, days=250)
        except Exception as exc:
            log.warning("kline_refresh_failed", error=repr(exc))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=3600)


async def _heartbeat_loop(stop: asyncio.Event, heartbeat: Heartbeat) -> None:
    while not stop.is_set():
        heartbeat.write()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=60)


async def _probe_quote_feeds(
    feed: QuoteFeed,
    tickers: list[tuple[str, str]],
    scan_feed: MarketScanFeed,
    sector_feed: SectorFeed,
    bark: BarkAlerter | None,
) -> None:
    probes: list[tuple[str, Callable[[], Awaitable[object]]]] = [
        ("quotes", lambda: feed.fetch(tickers)),
        ("market_scan", scan_feed.fetch),
        ("sectors", sector_feed.fetch_pct_changes),
    ]
    for name, probe in probes:
        try:
            result = await asyncio.wait_for(probe(), timeout=45)
            if not result:
                raise ValueError("empty upstream response")
            log.info("quote_startup_probe_ok", feed=name)
        except Exception as error:
            log.warning("quote_startup_probe_failed", feed=name, error=repr(error))
            if bark:
                await bark.send(
                    f"quote_watcher 启动自检失败: {name}",
                    repr(error),
                    level=AlertLevel.URGENT,
                )


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
