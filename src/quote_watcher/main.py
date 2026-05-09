"""Quote watcher entry point."""
from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from news_pipeline.config.loader import ConfigLoader
from news_pipeline.config.schema import MarketScansCfg
from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.emit.message import build_alert_message
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.feeds.market_scan import MarketScanFeed
from quote_watcher.feeds.sina import SinaFeed
from quote_watcher.scheduler.jobs import evaluate_alerts, poll_quotes, scan_market
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.store.kline import DailyKlineCache
from quote_watcher.store.tick import TickRing
from shared.observability.log import configure_logging, get_logger
from shared.push.dispatcher import PusherDispatcher
from shared.push.factory import build_pushers

BJ = ZoneInfo("Asia/Shanghai")
log = get_logger(__name__)


async def _ticker_poll_loop(
    stop: asyncio.Event,
    interval_sec: float,
    *,
    feed: SinaFeed,
    calendar: MarketCalendar,
    ring: TickRing,
    tickers: list[tuple[str, str]],
    engine: AlertEngine,
    dispatcher: PusherDispatcher,
    cn_alert_channels: list[str],
) -> None:
    while not stop.is_set():
        try:
            snaps = await poll_quotes(
                feed=feed, calendar=calendar, ring=ring, tickers=tickers,
                now=datetime.now(BJ),
            )
            if snaps:
                await evaluate_alerts(
                    snaps=snaps, engine=engine,
                    dispatcher=dispatcher, channels=cn_alert_channels,
                )
                snaps_by_ticker = {s.ticker: s for s in snaps}
                portfolio_verdicts = await engine.evaluate_portfolio(
                    snaps_by_ticker=snaps_by_ticker
                )
                for v in portfolio_verdicts:
                    msg = build_alert_message(v)
                    await dispatcher.dispatch(msg, channels=cn_alert_channels)
        except Exception as e:
            log.warning("ticker_loop_failed", error=str(e))
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
                feed=scan_feed, calendar=calendar,
                dispatcher=dispatcher, channels=cn_alert_channels,
                cfg=scan_cfg, now=datetime.now(BJ),
            )
        except Exception as e:
            log.warning("scan_loop_failed", error=str(e))
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
        c for c, ch in snap.channels.channels.items()
        if ch.market == "cn" and ch.enabled
    ]

    # === Daily K warmup for indicator rules ===
    kline_cache = DailyKlineCache(db)
    cn_tickers_codes = [e.ticker for e in snap.quote_watchlist.cn]
    if cn_tickers_codes:
        try:
            await kline_cache.load_for(cn_tickers_codes, days=250)
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

    feed = SinaFeed()
    calendar = MarketCalendar()
    ring = TickRing(max_per_ticker=1000)

    tickers: list[tuple[str, str]] = [
        (e.market, e.ticker) for e in snap.quote_watchlist.cn
    ]

    scan_feed = MarketScanFeed()
    scan_cfg = snap.quote_watchlist.market_scans.get("cn", MarketScansCfg())
    scan_interval_sec = float(os.environ.get("QUOTE_SCAN_INTERVAL_SEC", "60"))

    log.info(
        "quote_watcher_starting",
        tickers=len(tickers),
        alert_rules=len(snap.alerts.alerts),
        cn_channels=cn_alert_channels,
        poll_sec=poll_interval_sec,
        scan_sec=scan_interval_sec,
    )

    stop = asyncio.Event()

    def _on_signal(*_: object) -> None:
        log.info("shutdown_signal")
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _on_signal)

    ticker_task = asyncio.create_task(_ticker_poll_loop(
        stop, poll_interval_sec,
        feed=feed, calendar=calendar, ring=ring, tickers=tickers,
        engine=engine, dispatcher=dispatcher, cn_alert_channels=cn_alert_channels,
    ))
    scan_task = asyncio.create_task(_market_scan_loop(
        stop, scan_interval_sec,
        scan_feed=scan_feed, calendar=calendar, dispatcher=dispatcher,
        cn_alert_channels=cn_alert_channels, scan_cfg=scan_cfg,
    ))

    await stop.wait()
    await asyncio.gather(ticker_task, scan_task, return_exceptions=True)

    await db.close()
    log.info("quote_watcher_stopped")


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
