"""Start the event pipeline and its health jobs."""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from news_pipeline.config.loader import ConfigLoader, ConfigSnapshot
from news_pipeline.config.schema import SourceDef
from news_pipeline.health.smoke import build_smoke_report, run_smoke
from news_pipeline.health.source_health import check_source_health
from news_pipeline.ingest.store import ArticleStore
from news_pipeline.runtime import PipelineRuntime
from news_pipeline.scheduler.jobs import scrape_one_source
from news_pipeline.scheduler.runner import SchedulerRunner
from news_pipeline.scrapers.base import ScraperProtocol
from news_pipeline.scrapers.factory import build_registry
from news_pipeline.scrapers.registry import ScraperRegistry
from news_pipeline.storage.dao.metrics import MetricsDAO
from news_pipeline.storage.dao.retention import RetentionDAO
from news_pipeline.storage.dao.source_state import SourceStateDAO
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import Delivery
from shared.common.timeutil import utc_now
from shared.observability.alert import BarkAlerter
from shared.observability.heartbeat import Heartbeat
from shared.observability.log import configure_logging, get_logger
from shared.push.dispatcher import PusherDispatcher
from shared.push.factory import build_pushers

log = get_logger(__name__)


def register_jobs(
    runtime: PipelineRuntime,
    registry: ScraperRegistry,
    snap: ConfigSnapshot,
    heartbeat: Heartbeat,
    db_path: Path,
    bark: BarkAlerter | None,
) -> SchedulerRunner:
    runner = SchedulerRunner(heartbeat)
    state = SourceStateDAO(runtime.db)
    metrics = MetricsDAO(runtime.db)
    for sid in registry.list_ids():
        cfg = snap.sources.sources[sid]
        source_scraper = registry.get(sid)
        store = ArticleStore(runtime.raw)

        async def scrape(
            scraper: ScraperProtocol = source_scraper,
            source_cfg: SourceDef = cfg,
            source_store: ArticleStore = store,
        ) -> int:
            return await scrape_one_source(
                scraper=scraper,
                store=source_store,
                state_dao=state,
                cfg=source_cfg,
                metrics=metrics,
                bark=bark,
            )

        runner.add_interval(
            name=f"scrape_{sid}", seconds=cfg.interval_sec or 180, jitter=5, coro_factory=scrape
        )
    runner.add_interval(name="cluster_events", seconds=30, coro_factory=runtime.clusterer.process)
    runner.add_interval(name="assess_events", seconds=30, coro_factory=runtime.assessor.run)
    runner.add_interval(name="decide_events", seconds=10, coro_factory=runtime.decide_pending)
    runner.add_interval(name="deliver_outbox", seconds=10, coro_factory=runtime.outbox.run)
    for market in ("cn", "us"):
        for schedule in getattr(snap.app.scheduler.digest, market):
            hour, minute = map(int, schedule.at.split(":"))

            async def digest(
                market: str = market, at: str = schedule.at, tz: str = schedule.tz
            ) -> None:
                date = utc_now().astimezone(ZoneInfo(tz)).date().isoformat()
                await runtime.digest(market, f"{market}@{at}@{date}")

            runner.add_cron(
                name=f"digest_{market}_{schedule.at}",
                hour=hour,
                minute=minute,
                timezone=schedule.tz,
                coro_factory=digest,
            )
    hour, minute = map(int, snap.app.ops.report_at.split(":"))
    runner.add_cron(
        name="ops_report",
        hour=hour,
        minute=minute,
        coro_factory=lambda: runtime.ops_report(db_path),
    )
    runner.add_interval(
        name="source_health",
        seconds=300,
        coro_factory=lambda: check_source_health(state, snap.sources.sources, bark=bark),
    )

    async def write_heartbeat() -> None:
        heartbeat.write()

    runner.add_interval(name="heartbeat", seconds=60, coro_factory=write_heartbeat)
    retention = RetentionDAO(runtime.db)
    runner.add_cron(name="retention", hour=4, minute=10, coro_factory=retention.prune)
    runner.add_cron(name="vacuum", hour=4, minute=30, day="1", coro_factory=retention.vacuum)

    async def smoke() -> None:
        results = await run_smoke(registry, snap.sources, runtime.raw)
        await enqueue_smoke_report(runtime, snap, results, f"smoke@{utc_now().date()}")

    runner.add_cron(name="weekly_smoke", hour=20, minute=0, day_of_week="sun", coro_factory=smoke)
    return runner


async def enqueue_smoke_report(
    runtime: PipelineRuntime, snap: ConfigSnapshot, results: list[dict[str, Any]], slot: str
) -> None:
    channel = snap.app.ops.report_channel
    if channel in snap.channels.channels and snap.channels.channels[channel].enabled:
        await runtime.deliveries.enqueue(
            Delivery(
                kind="ops",
                channel=channel,
                payload=build_smoke_report(results).model_dump(mode="json"),
                digest_slot=slot,
            )
        )


async def initialize_scrapers(
    registry: ScraperRegistry, snap: ConfigSnapshot, heartbeat: Heartbeat
) -> None:
    for sid in registry.list_ids():
        initialize = getattr(registry.get(sid), "initialize", None)
        if initialize is None:
            continue
        heartbeat.write()
        try:
            await asyncio.wait_for(
                initialize(), timeout=snap.sources.sources[sid].fetch_timeout_sec
            )
        except ValueError:
            raise  # Unknown configured ticker is a startup configuration error.
        except Exception as error:
            log.warning("source_initialize_failed", source=sid, error=repr(error))


async def _amain() -> None:
    cfg_dir = Path(os.environ.get("NEWS_PIPELINE_CONFIG_DIR", "config"))
    db_path = Path(os.environ.get("NEWS_PIPELINE_DB", "data/news.db"))
    once = os.environ.get("NEWS_PIPELINE_ONCE", "0") == "1"
    configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"), json_output=True)
    snap = ConfigLoader(cfg_dir).load()
    sec_cfg = snap.sources.sources.get("sec_edgar")
    if sec_cfg and os.environ.get("SEC_USER_AGENT"):
        sec_cfg.options["user_agent"] = os.environ["SEC_USER_AGENT"]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    await db.initialize()
    runtime: PipelineRuntime | None = None
    runner: SchedulerRunner | None = None
    try:
        bark_url = snap.secrets.alert.get("bark_url")
        bark = BarkAlerter(bark_url) if bark_url else None
        runtime = PipelineRuntime(
            db, snap, PusherDispatcher(build_pushers(snap.channels, snap.secrets)), bark
        )
        registry = build_registry(snap.sources, snap.watchlist, snap.secrets)
        heartbeat = Heartbeat(
            Path(os.environ.get("HEARTBEAT_PATH", "data/heartbeat_news_pipeline.json"))
        )
        heartbeat.write()
        await initialize_scrapers(registry, snap, heartbeat)
        if once:
            state = SourceStateDAO(db)
            store = ArticleStore(runtime.raw)
            for sid in registry.list_ids():
                await scrape_one_source(
                    scraper=registry.get(sid),
                    store=store,
                    state_dao=state,
                    cfg=snap.sources.sources[sid],
                    bark=bark,
                )
            await runtime.process_v2()
            await runtime.outbox.run()
            return
        runner = register_jobs(runtime, registry, snap, heartbeat, db_path, bark)
        runner.start()
        stop = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        probes = await run_smoke(registry, snap.sources, runtime.raw)
        for probe in probes:
            log.info("startup_source_probe", **probe)
        await enqueue_smoke_report(runtime, snap, probes, f"startup_smoke@{utc_now().isoformat()}")
        await stop.wait()
    finally:
        if runner is not None:
            await runner.shutdown()
        if runtime is not None:
            await runtime.close()
        await db.close()
        log.info("shutdown_complete")


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
