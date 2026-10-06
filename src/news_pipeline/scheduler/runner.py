import asyncio
from collections.abc import Callable
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from shared.observability.heartbeat import Heartbeat
from shared.observability.log import get_logger

log = get_logger(__name__)


class SchedulerRunner:
    def __init__(self, heartbeat: Heartbeat | None = None) -> None:
        self._heartbeat = heartbeat
        self._sched = AsyncIOScheduler(timezone="UTC")
        self._running_tasks: set[asyncio.Task[Any]] = set()

    async def _run_job(self, name: str, coro_factory: Callable[[], Any]) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._running_tasks.add(task)
        try:
            await coro_factory()
        except Exception as e:
            log.error("job_failed", name=name, error=repr(e))
        finally:
            if self._heartbeat is not None:
                self._heartbeat.complete(name)
            if task is not None:
                self._running_tasks.discard(task)

    def add_interval(
        self,
        *,
        name: str,
        seconds: int,
        coro_factory: Callable[[], Any],
        jitter: int | None = None,
    ) -> None:
        async def _run() -> None:
            await self._run_job(name, coro_factory)

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
        day_of_week: str | None = None,
        day: str | None = None,
    ) -> None:
        async def _run() -> None:
            await self._run_job(name, coro_factory)

        self._sched.add_job(
            _run,
            trigger=CronTrigger(
                hour=hour,
                minute=minute,
                timezone=timezone,
                day_of_week=day_of_week,
                day=day,
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
        tasks = tuple(self._running_tasks)
        self._sched.shutdown(wait=True)
        # APScheduler schedules shutdown on the loop and does not await cancelled jobs.
        await asyncio.sleep(0)
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
