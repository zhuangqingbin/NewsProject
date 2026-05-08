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
from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.feeds.sina import SinaFeed
from quote_watcher.scheduler.jobs import evaluate_alerts, poll_quotes
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.store.tick import TickRing
from shared.observability.log import configure_logging, get_logger
from shared.push.dispatcher import PusherDispatcher
from shared.push.factory import build_pushers

BJ = ZoneInfo("Asia/Shanghai")
log = get_logger(__name__)


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

    tracker = StateTracker(dao=AlertStateDAO(db))
    engine = AlertEngine(rules=snap.alerts.alerts, tracker=tracker)

    feed = SinaFeed()
    calendar = MarketCalendar()
    ring = TickRing(max_per_ticker=1000)

    tickers: list[tuple[str, str]] = [
        (e.market, e.ticker) for e in snap.quote_watchlist.cn
    ]
    log.info(
        "quote_watcher_starting",
        tickers=len(tickers),
        poll_sec=poll_interval_sec,
        alert_rules=len(snap.alerts.alerts),
        cn_channels=cn_alert_channels,
    )

    stop = asyncio.Event()

    def _on_signal(*_: object) -> None:
        log.info("shutdown_signal")
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _on_signal)

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
        except Exception as e:
            log.warning("poll_iteration_failed", error=str(e))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=poll_interval_sec)

    await db.close()
    log.info("quote_watcher_stopped")


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
