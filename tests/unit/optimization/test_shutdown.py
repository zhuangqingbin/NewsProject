import asyncio

from news_pipeline.scheduler.runner import SchedulerRunner


async def test_scheduler_waits_for_job_cleanup_before_shutdown_returns():
    entered, cleaned = asyncio.Event(), asyncio.Event()

    async def work():
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    runner = SchedulerRunner()
    runner.add_interval(name="worker", seconds=3600, coro_factory=work)
    job = runner._sched.get_job("worker")
    runner.start()
    task = asyncio.create_task(job.func())
    await entered.wait()
    try:
        await runner.shutdown()
        assert cleaned.is_set() and task.done()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
