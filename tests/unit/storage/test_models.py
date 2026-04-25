from datetime import datetime

import pytest
from sqlmodel import select

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import (
    SQLModelBase,
    RawNews,
    NewsProcessed,
    Entity,
    NewsEntity,
    Relation,
    SourceState,
    PushLog,
    DigestBuffer,
    DeadLetter,
    ChartCache,
    AuditLog,
    DailyMetric,
)


@pytest.mark.asyncio
async def test_create_all_tables(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as conn:
        await conn.run_sync(SQLModelBase.metadata.create_all)
    async with db.session() as s:
        s.add(RawNews(source="finnhub", market="us",
                      url="https://x.com/1", url_hash="h1",
                      title="t", title_simhash=0,
                      fetched_at=datetime(2026, 4, 25),
                      published_at=datetime(2026, 4, 25),
                      status="pending"))
        await s.commit()
        rows = (await s.execute(select(RawNews))).scalars().all()
        assert len(rows) == 1
    await db.close()
