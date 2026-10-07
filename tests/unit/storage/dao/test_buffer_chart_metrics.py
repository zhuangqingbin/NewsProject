import pytest

from news_pipeline.storage.dao.metrics import MetricsDAO
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import SQLModelBase


@pytest.fixture
async def daos(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as c:
        await c.run_sync(SQLModelBase.metadata.create_all)
    yield MetricsDAO(db)
    await db.close()


@pytest.mark.asyncio
async def test_metrics_increment(daos):
    m = daos
    await m.increment(date_iso="2026-04-25", name="scrape_ok", dimensions="source=finnhub", delta=5)
    await m.increment(date_iso="2026-04-25", name="scrape_ok", dimensions="source=finnhub", delta=3)
    val = await m.get(date_iso="2026-04-25", name="scrape_ok", dimensions="source=finnhub")
    assert val == 8.0
