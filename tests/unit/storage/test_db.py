import pytest
from sqlalchemy import text

from news_pipeline.storage.db import Database


@pytest.mark.asyncio
async def test_create_engine_and_query(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.session() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
    await db.close()


@pytest.mark.asyncio
async def test_wal_mode_enabled(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.session() as session:
        result = await session.execute(text("PRAGMA journal_mode"))
        assert result.scalar() == "wal"
    await db.close()
