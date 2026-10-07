from datetime import timedelta
from unittest.mock import AsyncMock

from sqlalchemy import select

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.timeutil import utc_now
from news_pipeline.config.schema import SourceDef
from news_pipeline.ingest.store import ArticleStore
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.dao.source_state import SourceStateDAO
from news_pipeline.storage.models import RawNews


def article(n, *, simhash=100, source="sina_global"):
    now = utc_now()
    return RawArticle(
        source=source,
        market=Market.US,
        fetched_at=now,
        published_at=now - timedelta(minutes=40),
        url=f"https://example.com/{n}",
        url_hash=str(n),
        title="英伟达回购1500亿美元",
        title_simhash=simhash,
    )


async def test_store_keeps_duplicate_evidence_and_batches_urls(db):
    raw = RawNewsDAO(db)
    store = ArticleStore(raw)
    assert await store.save([article(1), article(1)], status="pending") == 1
    assert await store.save([article(1), article(2)], status="pending") == 1
    async with db.session() as session:
        rows = (await session.execute(select(RawNews).order_by(RawNews.id))).scalars().all()
    assert len(rows) == 2
    assert rows[1].status == "pending"
    assert rows[1].raw_meta == {}
    assert await raw.existing_url_hashes([str(n) for n in range(1200)]) == {"1", "2"}


async def test_seeded_and_v2_articles_have_independent_state(db):
    raw = RawNewsDAO(db)
    store = ArticleStore(raw)
    await store.save([article(1)], status="seeded")
    await store.save([article(2), article(3)], status="pending")
    assert [r.url_hash for r in await raw.list_v2_pending()] == ["2", "3"]
    assert len(await raw.list_pending()) == 2


async def test_backoff_resets_on_success(db):
    dao = SourceStateDAO(db)
    now = utc_now()
    for failures, minutes in enumerate([1, 2, 4, 8, 16, 30, 30], start=1):
        await dao.record_failure("test", error="TimeoutError()", base_interval=60, now=now)
        state = await dao.get("test")
        assert state.consecutive_failures == failures
        assert state.paused_until == (now + timedelta(minutes=minutes)).replace(tzinfo=None)
    await dao.record_success("test", new_items=1, now=now)
    state = await dao.get("test")
    assert state.consecutive_failures == 0
    assert state.paused_until is None
    assert state.last_item_at == now.replace(tzinfo=None)


async def test_health_only_alerts_on_transitions(db):
    from news_pipeline.health.source_health import check_source_health

    dao = SourceStateDAO(db)
    bark = AsyncMock()
    now = utc_now()
    cfg = SourceDef(max_silence_min=90, max_silence_off_min=180)
    for _ in range(5):
        await dao.record_failure("test", error="bad columns", base_interval=60, now=now)
    assert await check_source_health(dao, {"test": cfg}, bark=bark, now=now) == 1
    assert await check_source_health(dao, {"test": cfg}, bark=bark, now=now) == 0
    assert bark.send.await_count == 1
    await dao.record_success("test", new_items=1, now=now)
    assert await check_source_health(dao, {"test": cfg}, bark=bark, now=now) == 1
    assert bark.send.await_count == 2


async def test_empty_source_stays_down_without_false_recovery(db):
    from news_pipeline.health.source_health import check_source_health

    dao = SourceStateDAO(db)
    now = utc_now()
    await dao.record_success("empty", new_items=0, now=now)
    cfg = SourceDef(max_silence_min=90, max_silence_off_min=90)
    await check_source_health(dao, {"empty": cfg}, now=now + timedelta(minutes=91))
    await dao.record_success("empty", new_items=0, now=now + timedelta(minutes=95))
    assert await check_source_health(dao, {"empty": cfg}, now=now + timedelta(minutes=96)) == 0
    assert (await dao.get("empty")).health == "down"
