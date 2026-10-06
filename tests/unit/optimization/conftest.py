import pytest

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import SQLModelBase


@pytest.fixture
async def db(tmp_path):
    database = Database(f"sqlite+aiosqlite:///{tmp_path}/news.db")
    await database.initialize()
    async with database.engine.begin() as conn:
        await conn.run_sync(SQLModelBase.metadata.create_all)
    yield database
    await database.close()
