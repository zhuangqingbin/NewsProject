import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from news_pipeline.storage.models import Delivery, Event
from shared.common.contracts import CommonMessage
from shared.push.base import SendResult

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


def message():
    return CommonMessage(
        title="测试",
        summary="正文",
        source_label="来源",
        source_url="https://example.com/",
        badges=[],
        chart_url=None,
        deeplinks=[],
        market="cn",
    )


async def event(db, **values):
    row = Event(
        first_seen_at=NOW.replace(tzinfo=None),
        last_seen_at=NOW.replace(tzinfo=None),
        headline="事件",
        markets=["cn"],
        decision="push",
        **values,
    )
    async with db.session() as session:
        session.add(row)
        await session.commit()
    return row


def delivery(**values):
    return Delivery(
        kind="immediate",
        channel="feishu_cn",
        payload=message().model_dump(mode="json"),
        created_at=NOW.replace(tzinfo=None),
        **values,
    )


class Dispatcher:
    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [])
        self.calls = []

    async def dispatch(self, msg, *, channels):
        self.calls.append((msg, channels))
        ok = self.outcomes.pop(0) if self.outcomes else True
        return {channels[0]: SendResult(ok=ok, response_body="failure" if not ok else "")}


async def test_enqueue_is_idempotent_under_concurrent_calls(db):
    from news_pipeline.storage.dao.deliveries import DeliveryDAO

    ev = await event(db)
    dao = DeliveryDAO(db)
    ids = await asyncio.gather(*(dao.enqueue(delivery(event_id=ev.id)) for _ in range(8)))
    assert len(set(ids)) == 1
    assert (await dao.get(ids[0])).status == "pending"


async def test_enqueue_session_participates_in_caller_transaction(db):
    from news_pipeline.storage.dao.deliveries import DeliveryDAO

    ev = await event(db)
    async with db.session() as session:
        row_id = await DeliveryDAO.enqueue_session(session, delivery(event_id=ev.id))
        await session.rollback()
    assert await DeliveryDAO(db).get(row_id) is None


async def test_retry_schedule_survives_worker_restart(db):
    from news_pipeline.deliver.outbox import Outbox
    from news_pipeline.storage.dao.deliveries import DeliveryDAO

    dao = DeliveryDAO(db)
    row_id = await dao.enqueue(delivery())
    dispatcher = Dispatcher([False] * 5)
    at = NOW
    for n, delay in enumerate([10, 30, 120, 600, 1800], start=1):
        assert await Outbox(DeliveryDAO(db), dispatcher).run(now=at) == 1
        row = await dao.get(row_id)
        assert row.attempts == n
        assert row.next_attempt_at == (at + timedelta(seconds=delay)).replace(tzinfo=None)
        assert len(row.attempt_timestamps) == n
        assert row.status == ("failed" if n == 5 else "pending")
        if n < 5:
            assert await Outbox(dao, dispatcher).run(now=at + timedelta(seconds=delay - 1)) == 0
        at += timedelta(seconds=delay)
    assert len(dispatcher.calls) == 5


async def test_persistent_channel_rate_limit_counts_successes_after_restart(db):
    from news_pipeline.deliver.outbox import Outbox
    from news_pipeline.storage.dao.deliveries import DeliveryDAO

    dao = DeliveryDAO(db)
    for _ in range(22):
        await dao.enqueue(delivery())
    dispatcher = Dispatcher()
    for n in range(20):
        assert await Outbox(DeliveryDAO(db), dispatcher).run(now=NOW + timedelta(seconds=n)) == 1
    assert await Outbox(dao, dispatcher).run(now=NOW + timedelta(seconds=20)) == 0
    assert await Outbox(dao, dispatcher).run(now=NOW + timedelta(seconds=59)) == 0
    assert await Outbox(dao, dispatcher).run(now=NOW + timedelta(seconds=60)) == 1
    assert len(dispatcher.calls) == 21


async def test_concurrent_workers_reserve_one_attempt(db):
    from news_pipeline.deliver.outbox import Outbox
    from news_pipeline.storage.dao.deliveries import DeliveryDAO

    dao = DeliveryDAO(db)
    await dao.enqueue(delivery())
    dispatcher = Dispatcher()
    await asyncio.gather(Outbox(dao, dispatcher).run(now=NOW), Outbox(dao, dispatcher).run(now=NOW))
    assert len(dispatcher.calls) == 1


async def test_expiry_moves_event_to_digest_without_dispatch(db):
    from news_pipeline.deliver.outbox import Outbox
    from news_pipeline.storage.dao.deliveries import DeliveryDAO

    ev = await event(db)
    dao = DeliveryDAO(db)
    row_id = await dao.enqueue(delivery(event_id=ev.id, next_attempt_at=NOW + timedelta(hours=1)))
    dispatcher = Dispatcher()
    await Outbox(dao, dispatcher).run(now=NOW + timedelta(minutes=31))
    assert (await dao.get(row_id)).status == "expired"
    async with db.session() as session:
        assert (await session.get(Event, ev.id)).decision == "digest"
    assert not dispatcher.calls


async def test_digest_consumption_waits_for_all_channels(db):
    from news_pipeline.deliver.outbox import Outbox
    from news_pipeline.storage.dao.deliveries import DeliveryDAO

    selected = [await event(db) for _ in range(2)]
    dao = DeliveryDAO(db)
    for channel in ("feishu_cn", "telegram_cn"):
        await dao.enqueue(
            Delivery(
                kind="digest",
                channel=channel,
                market="cn",
                digest_slot="slot",
                payload=message().model_dump(mode="json"),
                created_at=NOW.replace(tzinfo=None),
                event_ids=[selected[0].id],
                consumed_event_ids=[row.id for row in selected],
            )
        )
    dispatcher = Dispatcher([True, False, True])
    assert await Outbox(dao, dispatcher).run(now=NOW) == 2
    async with db.session() as session:
        assert all(
            [(await session.get(Event, ev.id)).digest_delivery_id is None for ev in selected]
        )
    assert await Outbox(dao, dispatcher).run(now=NOW + timedelta(seconds=10)) == 1
    async with db.session() as session:
        assert all(
            [(await session.get(Event, ev.id)).digest_delivery_id is not None for ev in selected]
        )


async def test_shadow_digest_consumes_simulation_without_sending(db):
    from news_pipeline.deliver.outbox import Outbox
    from news_pipeline.storage.dao.deliveries import DeliveryDAO

    ev = await event(db)
    dao = DeliveryDAO(db)
    row_id = await dao.enqueue(
        Delivery(
            kind="digest",
            channel="feishu_cn",
            market="cn",
            digest_slot="shadow-slot",
            status="shadow",
            consumed_event_ids=[ev.id],
            payload=message().model_dump(mode="json"),
        )
    )
    dispatcher = Dispatcher()
    assert await Outbox(dao, dispatcher).run(now=NOW) == 0
    async with db.session() as session:
        assert (await session.get(Event, ev.id)).digest_delivery_id == row_id
    assert not dispatcher.calls


async def test_missing_dispatch_result_is_a_failed_attempt(db):
    from news_pipeline.deliver.outbox import Outbox
    from news_pipeline.storage.dao.deliveries import DeliveryDAO

    class MissingDispatcher:
        async def dispatch(self, msg, *, channels):
            return {}

    dao = DeliveryDAO(db)
    row_id = await dao.enqueue(delivery())
    await Outbox(dao, MissingDispatcher()).run(now=NOW)
    row = await dao.get(row_id)
    assert row.attempts == 1
    assert "missing" in row.last_error.lower()


@pytest.mark.parametrize(
    ("kind", "legacy_status", "legacy_channel", "same_event", "suppressed"),
    [
        ("immediate", "ok", "feishu_cn", True, True),
        ("immediate", "sent", "feishu_cn", True, True),
        ("immediate", "failed", "feishu_cn", True, False),
        ("immediate", "ok", "feishu_us", True, False),
        ("immediate", "ok", "feishu_cn", False, False),
        ("digest", "ok", "feishu_cn", True, False),
        ("ops", "ok", "feishu_cn", True, False),
    ],
)
async def test_only_matching_successful_legacy_immediate_sends_supersede_queue(
    db, kind, legacy_status, legacy_channel, same_event, suppressed
):
    from news_pipeline.deliver.outbox import Outbox
    from news_pipeline.storage.dao.deliveries import DeliveryDAO
    from news_pipeline.storage.dao.raw_news import RawNewsDAO
    from news_pipeline.storage.models import EventArticle, NewsProcessed, PushLog
    from tests.unit.optimization.test_ingest_health import article

    ev = await event(db)
    raw_id = await RawNewsDAO(db).insert_article(article("queued"))
    legacy_raw_id = raw_id if same_event else await RawNewsDAO(db).insert_article(article("other"))
    async with db.session() as session:
        session.add(EventArticle(event_id=ev.id, raw_id=raw_id, source="wire", joined_at=NOW))
        processed = NewsProcessed(
            raw_id=legacy_raw_id,
            summary="legacy send",
            event_type="other",
            sentiment="neutral",
            magnitude="low",
            confidence=0,
            score=70,
            is_critical=False,
            model_used="rules",
            extracted_at=NOW,
        )
        session.add(processed)
        await session.flush()
        session.add(
            PushLog(
                news_id=processed.id,
                channel=legacy_channel,
                status=legacy_status,
                sent_at=NOW,
            )
        )
        await session.commit()
    dao = DeliveryDAO(db)
    row_id = await dao.enqueue(
        Delivery(
            kind=kind,
            event_id=ev.id,
            channel="feishu_cn",
            payload=message().model_dump(mode="json"),
            created_at=NOW,
        )
    )
    dispatcher = Dispatcher()
    assert await Outbox(dao, dispatcher).run(now=NOW) == (0 if suppressed else 1)
    stored = await dao.get(row_id)
    assert stored.status == ("superseded" if suppressed else "sent")
    if suppressed:
        assert stored.sent_at is None and stored.attempt_timestamps == []
        assert not dispatcher.calls
