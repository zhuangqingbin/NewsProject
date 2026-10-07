from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from news_pipeline.config.loader import ConfigSnapshot
from news_pipeline.config.schema import (
    AppConfig,
    ChannelDef,
    ChannelsFile,
    QuoteWatchlistFile,
    RulesSection,
    SecretsFile,
    SourcesFile,
    TickerEntry,
    WatchlistFile,
)
from news_pipeline.runtime import PipelineRuntime
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.models import Delivery, Event, NewsProcessed, RawNews
from quote_watcher.alerts.rule import AlertsFile
from shared.common.timeutil import utc_now
from shared.push.base import SendResult
from shared.push.dispatcher import PusherDispatcher
from tests.unit.optimization.test_ingest_health import article


def snapshot(mode):
    return ConfigSnapshot(
        app=AppConfig(pipeline={"mode": mode}),
        watchlist=WatchlistFile(
            rules=RulesSection(us=[TickerEntry(ticker="NVDA", name="NVIDIA", aliases=["英伟达"])])
        ),
        channels=ChannelsFile(channels={"feishu_us": ChannelDef(type="feishu", market="us")}),
        sources=SourcesFile(sources={}),
        secrets=SecretsFile(),
        quote_watchlist=QuoteWatchlistFile(),
        alerts=AlertsFile(),
    )


async def test_v2_event_to_outbox_and_shadow_never_sends(db):
    for mode in ("shadow", "v2"):
        snap = snapshot(mode)
        pusher = AsyncMock(channel_id="feishu_us")
        pusher.send.return_value = SendResult(ok=True)
        runtime = PipelineRuntime(db, snap, PusherDispatcher({"feishu_us": pusher}))
        item = article(mode).model_copy(
            update={
                "title": "英伟达目标价上调至201美元" if mode == "v2" else "英伟达回购1500亿美元"
            }
        )
        await RawNewsDAO(db).insert_article(item)
        await runtime.process_v2()
        async with db.session() as session:
            rows = (await session.execute(select(Delivery).order_by(Delivery.id))).scalars().all()
            event = (
                (await session.execute(select(Event).order_by(Event.id.desc()))).scalars().first()
            )
        assert event.decision == "push"
        assert rows[-1].status == ("shadow" if mode == "shadow" else "pending")
        assert (await RawNewsDAO(db).find_by_url_hash(mode)).status == "pending"
        await runtime.outbox.run()
        assert pusher.send.await_count == (0 if mode == "shadow" else 1)
        await runtime.close()


@pytest.mark.parametrize("mode", ["legacy", "shadow"])
async def test_mode_rollback_pauses_news_outbox_until_v2_resumes(db, mode):
    pusher = AsyncMock(channel_id="feishu_us")
    pusher.send.return_value = SendResult(ok=True)
    dispatcher = PusherDispatcher({"feishu_us": pusher})
    runtime = PipelineRuntime(db, snapshot("v2"), dispatcher)
    try:
        await runtime.raw.insert_article(article("rollback-news"))
        await runtime.process_v2()
        immediate = (await runtime.deliveries.ready(utc_now()))[0]
        digest_id = await runtime.deliveries.enqueue(
            Delivery(
                kind="digest",
                channel="feishu_us",
                market="us",
                digest_slot="queued-before-rollback",
                payload=immediate.payload,
            )
        )
    finally:
        await runtime.close()

    rollback = PipelineRuntime(db, snapshot(mode), dispatcher)
    try:
        assert await rollback.outbox.run() == 0
        assert not pusher.send.await_count
        for delivery_id in (immediate.id, digest_id):
            row = await rollback.deliveries.get(delivery_id)
            assert row.status == "pending"
            assert row.attempt_timestamps == []
    finally:
        await rollback.close()

    resumed = PipelineRuntime(db, snapshot("v2"), dispatcher)
    try:
        at = utc_now()
        assert await resumed.outbox.run(now=at) == 1
        assert await resumed.outbox.run(now=at + timedelta(seconds=2)) == 1
        assert pusher.send.await_count == 2
        assert (await resumed.deliveries.get(immediate.id)).status == "sent"
        assert (await resumed.deliveries.get(digest_id)).status == "sent"
    finally:
        await resumed.close()


@pytest.mark.parametrize("mode", ["legacy", "shadow"])
async def test_ops_outbox_bypasses_more_than_one_page_of_paused_news(db, mode):
    from tests.unit.optimization.test_outbox import message

    at = utc_now().replace(tzinfo=None)
    news = [
        Delivery(
            kind="immediate" if n % 2 else "digest",
            channel="feishu_us",
            created_at=at - timedelta(minutes=1),
            payload=message().model_dump(mode="json"),
        )
        for n in range(101)
    ]
    ops = Delivery(
        kind="ops",
        channel="feishu_us",
        created_at=at,
        payload=message().model_copy(update={"title": "运维日报"}).model_dump(mode="json"),
    )
    async with db.session() as session:
        session.add_all([*news, ops])
        await session.commit()
    pusher = AsyncMock(channel_id="feishu_us")
    pusher.send.return_value = SendResult(ok=True)
    runtime = PipelineRuntime(db, snapshot(mode), PusherDispatcher({"feishu_us": pusher}))
    try:
        assert await runtime.outbox.run(now=at) == 1
        assert pusher.send.await_count == 1
        assert pusher.send.call_args.args[0].title == "运维日报"
        assert (await runtime.deliveries.get(ops.id)).status == "sent"
        async with db.session() as session:
            paused = (
                await session.execute(select(Delivery).where(Delivery.kind != "ops"))
            ).scalars()
            assert all(row.status == "pending" and not row.attempt_timestamps for row in paused)
    finally:
        await runtime.close()


@pytest.mark.parametrize("mode", ["legacy", "shadow"])
async def test_successful_v2_delivery_is_not_sent_again_after_rollback(db, mode):
    pusher = AsyncMock(channel_id="feishu_us")
    pusher.send.return_value = SendResult(ok=True)
    dispatcher = PusherDispatcher({"feishu_us": pusher})
    runtime = PipelineRuntime(db, snapshot("v2"), dispatcher)
    try:
        raw_id = await runtime.raw.insert_article(article("sent-before-rollback"))
        await runtime.process_v2()
        assert await runtime.outbox.run() == 1
        assert pusher.send.await_count == 1
        raw = await runtime.raw.get(raw_id)
        assert raw.status == "pending" and raw.v2_state == "clustered"
    finally:
        await runtime.close()

    rollback = PipelineRuntime(db, snapshot(mode), dispatcher)
    try:
        assert await rollback.process_legacy() == 1
        assert pusher.send.await_count == 1
        async with db.session() as session:
            proc = (await session.execute(select(NewsProcessed))).scalar_one()
            raw = await session.get(RawNews, raw_id)
        assert proc.push_status == "dup"
        assert raw.status == "processed" and raw.v2_state == "clustered"
    finally:
        await rollback.close()


def test_scheduler_registers_modes_and_market_timezones(tmp_path):
    from unittest.mock import MagicMock

    from news_pipeline.main import register_jobs
    from news_pipeline.scrapers.registry import ScraperRegistry
    from shared.observability.heartbeat import Heartbeat

    for mode in ("legacy", "shadow", "v2"):
        runtime = MagicMock(mode=mode)
        runtime.db = MagicMock()
        runner = register_jobs(
            runtime,
            ScraperRegistry(),
            snapshot(mode),
            Heartbeat(tmp_path / "heartbeat.json"),
            tmp_path / "news.db",
            None,
        )
        jobs = {job.id: job for job in runner._sched.get_jobs()}
        assert ("process_pending" in jobs) == (mode != "v2")
        assert ("cluster_events" in jobs) == (mode != "legacy")
        assert "deliver_outbox" in jobs
        assert str(jobs["digest_us_16:27"].trigger.timezone) == "America/New_York"
        assert str(jobs["digest_cn_20:57"].trigger.timezone) == "Asia/Shanghai"
        assert jobs["retention"] and jobs["vacuum"] and jobs["weekly_smoke"]


async def test_decision_waits_for_reassessment_when_evidence_changes(db):
    runtime = PipelineRuntime(db, snapshot("v2"), PusherDispatcher({}))
    ev = Event(
        first_seen_at=article(1).published_at,
        last_seen_at=article(1).published_at,
        headline="英伟达回购",
        markets=["us"],
        subject_tickers=["NVDA"],
        assess_status="failed",
        rule_decision="push",
    )
    async with db.session() as session:
        session.add(ev)
        await session.commit()
    original = runtime.events.list_undecided

    async def changed():
        rows = await original()
        await runtime.events.update(ev.id, assess_status="pending", article_count=2)
        return rows

    runtime.events.list_undecided = changed
    try:
        assert await runtime.decide_pending() == 0
        current = await runtime.events.get(ev.id)
        assert current.decision is None
        assert current.assess_status == "pending"
        from shared.common.timeutil import utc_now

        assert await runtime.deliveries.ready(utc_now()) == []
    finally:
        await runtime.close()


async def test_repeat_merge_rejects_stale_assessment(db):
    from news_pipeline.storage.dao.events import EventsDAO

    dao = EventsDAO(db)
    target = Event(
        first_seen_at=article(1).published_at,
        last_seen_at=article(1).published_at,
        headline="主事件",
    )
    source = Event(
        first_seen_at=article(1).published_at,
        last_seen_at=article(1).published_at,
        headline="重复事件",
        assess_status="done",
    )
    async with db.session() as session:
        session.add_all([source, target])
        await session.commit()
    await dao.update(source.id, article_count=2, assess_status="pending")
    assert not await dao.merge_repeat(source.id, target.id, expected_article_count=1)
    assert (await dao.get(source.id)).article_count == 2


async def test_each_scraper_keeps_its_own_ingestion_statistics(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from news_pipeline.config.schema import SourceDef
    from news_pipeline.main import register_jobs
    from news_pipeline.scrapers.registry import ScraperRegistry
    from shared.observability.heartbeat import Heartbeat

    snap = snapshot("v2")
    registry = ScraperRegistry()
    for sid in ("one", "two"):
        scraper = MagicMock(source_id=sid)
        registry.register(scraper)
        snap.sources.sources[sid] = SourceDef(interval_sec=30)
    stores = []

    async def scrape(**kwargs):
        stores.append(kwargs["store"])
        return 1

    monkeypatch.setattr("news_pipeline.main.scrape_one_source", scrape)
    runtime = MagicMock(mode="v2")
    runner = register_jobs(
        runtime, registry, snap, Heartbeat(tmp_path / "heart.json"), tmp_path / "news.db", None
    )
    for job in runner._sched.get_jobs():
        if job.id.startswith("scrape_"):
            await job.func()
    assert len(stores) == 2 and stores[0] is not stores[1]
