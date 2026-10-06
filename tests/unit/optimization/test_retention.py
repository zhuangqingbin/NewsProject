from datetime import UTC, datetime, timedelta
from importlib import import_module

from sqlalchemy import select, text

from news_pipeline.storage.models import (
    Delivery,
    Event,
    EventArticle,
    LLMCall,
    NewsProcessed,
    RawNews,
)

NOW = datetime(2026, 10, 6, 10, tzinfo=UTC)


def raw(index, days, *, status="pending", v2_state=None):
    at = (NOW - timedelta(days=days)).replace(tzinfo=None)
    return RawNews(
        id=index,
        source="wire",
        market="cn",
        url=f"https://example.com/{index}",
        url_hash=str(index),
        title=f"News {index}",
        fetched_at=at,
        published_at=at,
        status=status,
        v2_state=v2_state,
    )


def event(index, days):
    at = (NOW - timedelta(days=days)).replace(tzinfo=None)
    return Event(id=index, first_seen_at=at, last_seen_at=at, headline=f"Event {index}")


def delivery(index, days, *, status="sent", event_id=None):
    return Delivery(
        id=index,
        kind="immediate",
        event_id=event_id,
        channel=f"channel{index}",
        status=status,
        created_at=(NOW - timedelta(days=days)).replace(tzinfo=None),
    )


async def test_retention_thresholds_and_referenced_history_are_preserved(db):
    module = import_module("news_pipeline.storage.dao.retention")
    async with db.session() as session:
        session.add_all(
            [
                raw(1, 61, v2_state="skipped_rules"),
                raw(2, 59, v2_state="skipped_low"),
                raw(3, 61, status="duplicate"),
                raw(4, 61, status="seeded"),
                raw(5, 366),
                raw(6, 364, v2_state="legacy"),
                raw(7, 61, v2_state="skipped_rules"),
                raw(8, 366, status="seeded"),
                raw(9, 366),
                raw(10, 61, status="skipped_rules", v2_state="legacy"),
                event(1, 366),
                event(2, 10),
            ]
        )
        await session.commit()
        session.add_all(
            [
                NewsProcessed(
                    id=1,
                    raw_id=8,
                    summary="legacy history",
                    event_type="other",
                    sentiment="neutral",
                    magnitude="low",
                    confidence=0.9,
                    score=50,
                    is_critical=False,
                    model_used="rules",
                    extracted_at=NOW.replace(tzinfo=None),
                ),
                EventArticle(
                    event_id=1, raw_id=9, source="wire", joined_at=NOW.replace(tzinfo=None)
                ),
                EventArticle(
                    event_id=2, raw_id=7, source="wire", joined_at=NOW.replace(tzinfo=None)
                ),
                delivery(1, 1, event_id=1),
                delivery(2, 31, status="shadow"),
                delivery(3, 366),
                delivery(4, 31, status="pending"),
                delivery(5, 364),
                LLMCall(
                    id=1,
                    purpose="assess",
                    model="test",
                    prompt_version="v1",
                    created_at=(NOW - timedelta(days=181)).replace(tzinfo=None),
                ),
                LLMCall(
                    id=2,
                    purpose="assess",
                    model="test",
                    prompt_version="v1",
                    created_at=(NOW - timedelta(days=179)).replace(tzinfo=None),
                ),
            ]
        )
        await session.commit()
    dao = module.RetentionDAO(db)
    counts = await dao.prune(now=NOW)
    assert counts == {
        "raw_news": 6,
        "events": 1,
        "event_articles": 1,
        "deliveries": 3,
        "llm_calls": 1,
    }
    async with db.session() as session:
        assert {r.id for r in (await session.execute(select(RawNews))).scalars()} == {
            2,
            6,
            7,
            8,
        }
        assert {r.id for r in (await session.execute(select(Event))).scalars()} == {2}
        assert {r.id for r in (await session.execute(select(Delivery))).scalars()} == {4, 5}
        assert {r.id for r in (await session.execute(select(NewsProcessed))).scalars()} == {1}
        assert (await session.execute(text("PRAGMA foreign_key_check"))).all() == []
    assert all(value == 0 for value in (await dao.prune(now=NOW)).values())


async def test_vacuum_runs_outside_retention_transaction(db):
    module = import_module("news_pipeline.storage.dao.retention")
    dao = module.RetentionDAO(db)
    await dao.prune(now=NOW)
    await dao.vacuum()
    async with db.session() as session:
        assert (await session.execute(text("PRAGMA integrity_check"))).scalar() == "ok"


async def test_legacy_skipped_rows_expire_after_60_days_but_references_survive(db):
    module = import_module("news_pipeline.storage.dao.retention")
    async with db.session() as session:
        session.add_all(
            [
                raw(1, 61, status="skipped_rules"),
                raw(2, 61, status="skipped_low"),
                raw(3, 59, status="skipped_rules"),
                raw(4, 60, status="skipped_low"),
                raw(5, 61, status="skipped_rules"),
                raw(6, 61, status="skipped_low"),
                event(1, 10),
            ]
        )
        await session.commit()
        session.add_all(
            [
                NewsProcessed(
                    raw_id=5,
                    summary="legacy history",
                    event_type="other",
                    sentiment="neutral",
                    magnitude="low",
                    confidence=0.9,
                    score=50,
                    is_critical=False,
                    model_used="rules",
                    extracted_at=NOW.replace(tzinfo=None),
                ),
                EventArticle(
                    event_id=1, raw_id=6, source="wire", joined_at=NOW.replace(tzinfo=None)
                ),
            ]
        )
        await session.commit()
    counts = await module.RetentionDAO(db).prune(now=NOW)
    assert counts["raw_news"] == 2
    async with db.session() as session:
        remaining = (await session.execute(select(RawNews))).scalars()
        assert {row.id for row in remaining} == {3, 4, 5, 6}
        assert (await session.execute(text("PRAGMA foreign_key_check"))).all() == []
