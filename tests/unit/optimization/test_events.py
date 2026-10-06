import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from news_pipeline.config.schema import RulesSection, TickerEntry
from news_pipeline.events.clusterer import EventClusterer
from news_pipeline.rules.engine import RulesEngine
from news_pipeline.storage.dao.events import EventsDAO
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.models import Event, EventArticle
from tests.unit.optimization.test_ingest_health import article


def engine():
    return RulesEngine(
        RulesSection(us=[TickerEntry(ticker="NVDA", name="NVIDIA", aliases=["英伟达"])], cn=[])
    )


async def test_cluster_across_sources_and_rebuild_after_restart(db):
    raw = RawNewsDAO(db)
    for n, title, source in [
        (1, "英伟达：将股票回购授权规模增加1500亿美元", "sina_global"),  # noqa: RUF001
        (2, "英伟达宣布将股票回购授权规模提高1500亿美元", "futu_global"),
    ]:
        item = article(n, source=source).model_copy(update={"title": title})
        await raw.insert_article(item)
    events = EventsDAO(db)
    clusterer = EventClusterer(events, raw, engine())
    assert await clusterer.process() == 2
    rows = await events.list_recent()
    assert len(rows) == 1
    assert rows[0].article_count == 2 and rows[0].source_count == 2
    assert rows[0].rule_decision == "push"
    assert all(
        r.v2_state == "clustered" and r.status == "pending"
        for r in [await raw.get(1), await raw.get(2)]
    )
    await raw.insert_article(
        article(3).model_copy(update={"title": "英伟达宣布将股票回购授权规模提高1500亿美元"})
    )
    assert await EventClusterer(events, raw, engine()).process() == 1
    assert len(await events.list_recent()) == 1
    assert (await events.get(rows[0].id)).article_count == 3


async def test_cluster_time_window_and_idempotency(db):
    raw = RawNewsDAO(db)
    first = article(1)
    await raw.insert_article(first)
    await raw.insert_article(
        article(2).model_copy(update={"published_at": first.published_at + timedelta(hours=7)})
    )
    clusterer = EventClusterer(EventsDAO(db), raw, engine())
    assert await clusterer.process() == 2
    assert await clusterer.process() == 0
    assert len(await EventsDAO(db).list_recent(hours=24)) == 2


async def test_repeat_reparents_articles_and_sources(db):
    raw = RawNewsDAO(db)
    await raw.insert_article(article(1))
    await raw.insert_article(
        article(2, source="futu_global").model_copy(update={"title": "英伟达发布新产品"})
    )
    dao = EventsDAO(db)
    await EventClusterer(dao, raw, engine()).process()
    rows = await dao.list_recent()
    assert len(rows) == 2
    await dao.merge_repeat(rows[1].id, rows[0].id)
    target = await dao.get(rows[0].id)
    assert target.article_count == 2 and target.source_count == 2
    assert (await dao.get(rows[1].id)).decision == "drop"
    async with db.session() as session:
        links = (await session.execute(select(EventArticle))).scalars().all()
    assert {link.event_id for link in links} == {target.id}


async def test_high_announcements_in_one_batch_share_card_event(db):
    raw = RawNewsDAO(db)
    titles = [
        "宁德时代：员工持股计划草案",  # noqa: RUF001
        "宁德时代：员工持股计划草案摘要",  # noqa: RUF001
        "宁德时代：股份回购方案",  # noqa: RUF001
    ]
    for index, title in enumerate(titles):
        item = article(index, source="juchao").model_copy(
            update={
                "market": __import__("news_pipeline.common.enums", fromlist=["Market"]).Market.CN,
                "title": title,
                "raw_meta": {"code": "300750"},
            }
        )
        await raw.insert_article(item)
    dao = EventsDAO(db)
    await EventClusterer(dao, raw, engine()).process()
    events = await dao.list_recent()
    assert len(events) == 1
    assert events[0].article_count == 3 and events[0].rule_reason == "tier:high"


async def test_new_source_hint_reassesses_skipped_event(db):
    raw = RawNewsDAO(db)
    dao = EventsDAO(db)
    first = article(1).model_copy(update={"title": "美联储宣布降息"})
    await raw.insert_article(first)
    await EventClusterer(dao, raw, engine()).process()
    ev = (await dao.list_recent())[0]
    assert ev.assess_status == "skipped"
    await dao.update(ev.id, decision="digest")
    second = article(2, source="wallstreetcn").model_copy(
        update={"title": first.title, "raw_meta": {"score": 2}}
    )
    await raw.insert_article(second)
    await EventClusterer(dao, raw, engine()).process()
    changed = await dao.get(ev.id)
    assert changed.importance_hint == 2 and changed.assess_status == "pending"
    assert changed.decision is None


async def test_repeat_merges_first_party_representative_and_tier(db):
    raw = RawNewsDAO(db)
    await raw.insert_article(article(1))
    await raw.insert_article(
        article(2, source="sec_edgar").model_copy(
            update={
                "title": "NVDA 10-Q：季度业绩报告",  # noqa: RUF001
                "raw_meta": {"ticker": "NVDA", "form": "10-Q"},
            }
        )
    )
    dao = EventsDAO(db)
    await EventClusterer(dao, raw, engine()).process()
    target, source = await dao.list_recent()
    assert source.first_party and source.rule_reason == "tier:high"
    await dao.merge_repeat(source.id, target.id)
    target = await dao.get(target.id)
    assert target.headline == source.headline and target.rule_reason == "tier:high"
    assert target.first_party and target.subject_tickers == source.subject_tickers
    assert target.rank_score >= source.rank_score


async def test_every_database_connection_enforces_foreign_keys(db):
    from sqlalchemy import text

    async with db.engine.connect() as first, db.engine.connect() as second:
        assert (await first.execute(text("PRAGMA foreign_keys"))).scalar() == 1
        assert (await second.execute(text("PRAGMA foreign_keys"))).scalar() == 1


async def test_cluster_index_redirects_after_repeat_merge(db):
    raw = RawNewsDAO(db)
    dao = EventsDAO(db)
    clusterer = EventClusterer(dao, raw, engine())
    titles = [
        "英伟达追加1500亿美元回购额度 将在2028财年内完成全部剩余回购额度",
        "再增1500亿美元！英伟达2350亿美元回购授权创纪录 够买下一个贵州茅台",  # noqa: RUF001
    ]
    for n, title in enumerate(titles):
        await raw.insert_article(article(n).model_copy(update={"title": title}))
    await clusterer.process()
    target, duplicate = await dao.list_recent()
    await dao.merge_repeat(duplicate.id, target.id)
    await raw.insert_article(article(3).model_copy(update={"title": titles[1]}))
    await clusterer.process()
    assert len(await dao.list_recent()) == 2
    assert (await dao.get(target.id)).article_count == 3


async def repeat_events(db):
    raw = RawNewsDAO(db)
    rows = []
    for n in range(1, 4):
        item = article(n, source=f"source{n}")
        raw_id = await raw.insert_article(item)
        event = Event(
            headline=f"事件{n}",
            first_seen_at=item.published_at.replace(tzinfo=None),
            last_seen_at=item.published_at.replace(tzinfo=None),
            assess_status="done",
            novelty="new",
            sources=[item.source],
        )
        async with db.session() as session:
            session.add(event)
            await session.flush()
            session.add(
                EventArticle(
                    event_id=event.id, raw_id=raw_id, source=item.source, joined_at=item.fetched_at
                )
            )
            await session.commit()
        rows.append(event)
    return rows


async def test_repeat_follows_target_already_merged_into_canonical_event(db):
    source, target, canonical = await repeat_events(db)
    dao = EventsDAO(db)
    await dao.update(target.id, novelty="repeat", same_as_event_id=canonical.id)
    await dao.update(source.id, novelty="repeat", same_as_event_id=target.id)
    assert await dao.merge_repeat(target.id, canonical.id, expected_article_count=1)

    assert await dao.merge_repeat(source.id, target.id, expected_article_count=1)

    saved = await dao.get(canonical.id)
    assert saved.article_count == 3 and saved.source_count == 3
    assert (await dao.get(source.id)).same_as_event_id == canonical.id
    async with db.session() as session:
        links = (await session.execute(select(EventArticle))).scalars().all()
    assert {link.event_id for link in links} == {canonical.id}


@pytest.mark.parametrize(
    "failure", ["missing", "ordinary_drop", "cycle", "self", "through_source", "dangling"]
)
async def test_invalid_repeat_target_reassesses_source_without_moving_articles(db, failure):
    source, target, other = await repeat_events(db)
    dao = EventsDAO(db)
    target_id = target.id
    if failure == "missing":
        target_id = 99999
    elif failure == "self":
        target_id = source.id
    elif failure == "ordinary_drop":
        await dao.update(target.id, decision="drop", decision_reason="materiality=1")
    else:
        destination = (
            source.id
            if failure == "through_source"
            else 99999
            if failure == "dangling"
            else other.id
        )
        await dao.update(
            target.id, decision="drop", decision_reason="repeat", same_as_event_id=destination
        )
        if failure == "cycle":
            await dao.update(
                other.id, decision="drop", decision_reason="repeat", same_as_event_id=target.id
            )
    await dao.update(source.id, novelty="repeat", same_as_event_id=target_id)

    assert not await dao.merge_repeat(source.id, target_id, expected_article_count=1)

    saved = await dao.get(source.id)
    assert saved.assess_status == "pending" and saved.decision is None
    assert saved.novelty == "new" and saved.same_as_event_id is None
    assert saved.article_count == 1
    assert [row.id for row in await dao.articles(source.id)] == [1]


@pytest.mark.parametrize("changed", ["count", "original_target"])
async def test_repeat_chain_keeps_original_source_version_guard(db, changed):
    source, target, canonical = await repeat_events(db)
    dao = EventsDAO(db)
    await dao.update(target.id, novelty="repeat", same_as_event_id=canonical.id)
    assert await dao.merge_repeat(target.id, canonical.id, expected_article_count=1)
    await dao.update(
        source.id,
        novelty="repeat",
        same_as_event_id=canonical.id if changed == "original_target" else target.id,
        article_count=2 if changed == "count" else 1,
    )

    assert not await dao.merge_repeat(source.id, target.id, expected_article_count=1)

    saved = await dao.get(source.id)
    assert saved.assess_status == "done" and saved.decision is None
    assert saved.same_as_event_id == (canonical.id if changed == "original_target" else target.id)
    assert (await dao.get(canonical.id)).article_count == 2


async def test_concurrent_repeat_merges_count_source_articles_once(db):
    source, target, _ = await repeat_events(db)
    dao = EventsDAO(db)
    await dao.update(source.id, novelty="repeat", same_as_event_id=target.id)

    merged = await asyncio.gather(
        *(
            EventsDAO(db).merge_repeat(source.id, target.id, expected_article_count=1)
            for _ in range(2)
        )
    )

    assert sorted(merged) == [False, True]
    assert (await dao.get(target.id)).article_count == 2
    assert (await dao.get(source.id)).article_count == 0
