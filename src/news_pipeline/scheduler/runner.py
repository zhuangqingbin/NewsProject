from collections.abc import Callable
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from shared.observability.log import get_logger

log = get_logger(__name__)


class SchedulerRunner:
    def __init__(self) -> None:
        self._sched = AsyncIOScheduler(timezone="UTC")

    def add_interval(
        self,
        *,
        name: str,
        seconds: int,
        coro_factory: Callable[[], Any],
        jitter: int | None = None,
    ) -> None:
        async def _run() -> None:
            try:
                await coro_factory()
            except Exception as e:
                log.error("job_failed", name=name, error=str(e))

        self._sched.add_job(
            _run,
            trigger=IntervalTrigger(seconds=seconds, jitter=jitter),
            id=name,
            name=name,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def add_cron(
        self,
        *,
        name: str,
        hour: int,
        minute: int,
        coro_factory: Callable[[], Any],
        timezone: str = "Asia/Shanghai",
    ) -> None:
        async def _run() -> None:
            try:
                await coro_factory()
            except Exception as e:
                log.error("job_failed", name=name, error=str(e))

        self._sched.add_job(
            _run,
            trigger=CronTrigger(
                hour=hour,
                minute=minute,
                timezone=timezone,
            ),
            id=name,
            name=name,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def start(self) -> None:
        self._sched.start()
        log.info("scheduler_started", jobs=[j.id for j in self._sched.get_jobs()])

    async def shutdown(self) -> None:
        self._sched.shutdown(wait=True)
