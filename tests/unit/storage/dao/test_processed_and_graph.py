from datetime import datetime

import pytest

from news_pipeline.storage.dao.entities import EntitiesDAO
from news_pipeline.storage.dao.news_processed import NewsProcessedDAO
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.dao.relations import RelationsDAO
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import SQLModelBase


@pytest.fixture
async def daos(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as c:
        await c.run_sync(SQLModelBase.metadata.create_all)
    yield (RawNewsDAO(db), NewsProcessedDAO(db), EntitiesDAO(db), RelationsDAO(db))
    await db.close()


@pytest.mark.asyncio
async def test_insert_processed_and_link_entities(daos):
    raw, proc, ents, rels = daos
    raw_id = await raw.insert(
        source="x",
        market="us",
        url="https://x/1",
        url_hash="h1",
        title="t",
        title_simhash=0,
        body=None,
        raw_meta={},
        fetched_at_iso="2026-04-25T00:00:00",
        published_at_iso="2026-04-25T00:00:00",
    )
    pid = await proc.insert(
        raw_id=raw_id,
        summary="s",
        event_type="policy",
        sentiment="bearish",
        magnitude="high",
        confidence=0.9,
        key_quotes=["q"],
        score=80.0,
        is_critical=True,
        rule_hits=["price_5pct"],
        llm_reason=None,
        model_used="haiku",
        extracted_at=datetime(2026, 4, 25),
    )
    nv_id = await ents.upsert(
        type="company", name="NVIDIA", ticker="NVDA", market="us", aliases=["NVDA"]
    )
    tsm_id = await ents.upsert(type="company", name="TSMC", ticker="TSM", market="us", aliases=[])
    await ents.link_news(news_id=pid, entity_id=nv_id, role="subject", salience=0.95)
    await rels.insert(
        subject_id=nv_id, predicate="supplies", object_id=tsm_id, source_news_id=pid, confidence=0.9
    )

    found_subject = await ents.find(type="company", name="NVIDIA")
    assert found_subject is not None and found_subject.id == nv_id
    rel_rows = await rels.list_for_entity(nv_id)
    assert len(rel_rows) == 1
