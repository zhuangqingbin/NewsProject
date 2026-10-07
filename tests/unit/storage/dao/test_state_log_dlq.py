from datetime import UTC, datetime, timedelta

import pytest

from news_pipeline.storage.dao.source_state import SourceStateDAO
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import SQLModelBase


@pytest.fixture
async def daos(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as c:
        await c.run_sync(SQLModelBase.metadata.create_all)
    yield SourceStateDAO(db)
    await db.close()


@pytest.mark.asyncio
async def test_source_state_pause(daos):
    src = daos
    until = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=30)
    await src.set_paused("xueqiu", until=until, error="anti_crawl")
    assert await src.is_paused("xueqiu") is True
