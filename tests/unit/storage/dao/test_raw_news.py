import pytest

from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import SQLModelBase


@pytest.fixture
async def dao(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as conn:
        await conn.run_sync(SQLModelBase.metadata.create_all)
    yield RawNewsDAO(db)
    await db.close()


@pytest.mark.asyncio
async def test_insert_and_find_by_url_hash(dao):
    new_id = await dao.insert(
        source="finnhub",
        market="us",
        url="https://example.com/1",
        url_hash="hashA",
        title="t",
        title_simhash=12345,
        body="b",
        raw_meta={"x": 1},
        fetched_at_iso="2026-04-25T00:00:00",
        published_at_iso="2026-04-25T00:00:00",
    )
    assert new_id > 0
    found = await dao.find_by_url_hash("hashA")
    assert found is not None
    assert found.title == "t"


@pytest.mark.asyncio
async def test_pending_query(dao):
    await dao.insert(
        source="x",
        market="us",
        url="https://x/1",
        url_hash="h1",
        title="a",
        title_simhash=1,
        body=None,
        raw_meta={},
        fetched_at_iso="2026-04-25T00:00:00",
        published_at_iso="2026-04-25T00:00:00",
    )
    items = await dao.list_pending(limit=10)
    assert len(items) == 1


@pytest.mark.asyncio
async def test_simhash_neighbor_lookup(dao):
    await dao.insert(
        source="x",
        market="us",
        url="https://x/1",
        url_hash="h1",
        title="t1",
        title_simhash=0xFFFF0000,
        body=None,
        raw_meta={},
        fetched_at_iso="2026-04-25T00:00:00",
        published_at_iso="2026-04-25T00:00:00",
    )
    candidates = await dao.list_recent_simhashes(window_hours=24)
    assert any(s == 0xFFFF0000 for _id, s in candidates)
