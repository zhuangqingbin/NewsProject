import pytest

from news_pipeline.storage.dao.digest_buffer import DigestBufferDAO
from news_pipeline.storage.dao.metrics import MetricsDAO
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import SQLModelBase


@pytest.fixture
async def daos(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as c:
        await c.run_sync(SQLModelBase.metadata.create_all)
    yield (DigestBufferDAO(db), MetricsDAO(db))
    await db.close()


@pytest.mark.asyncio
async def test_digest_enqueue_and_consume(daos):
    buf, _ = daos
    # digest_buffer.news_id FK → news_processed; insert prerequisite rows
    from sqlalchemy import text

    async with buf._db.session() as s:
        await s.execute(
            text(
                "INSERT INTO raw_news (id, source, market, url, url_hash, title,"
                " title_simhash, fetched_at, published_at, status)"
                " VALUES (1,'x','us','https://x','h1','t',0,'2026-04-25','2026-04-25','pending')"
            )
        )
        await s.execute(
            text(
                "INSERT INTO news_processed (id, raw_id, summary, event_type, sentiment,"
                " magnitude, confidence, score, is_critical, model_used, extracted_at, push_status)"
                " VALUES (1,1,'s','other','neutral','low',0.5,50,0,'m','2026-04-25','pending')"
            )
        )
        await s.commit()
    await buf.enqueue(news_id=1, market="us", scheduled_digest="morning_us")
    pending = await buf.list_pending("morning_us")
    assert len(pending) == 1
    await buf.mark_consumed([pending[0].id])  # type: ignore[list-item]
    pending2 = await buf.list_pending("morning_us")
    assert len(pending2) == 0


@pytest.mark.asyncio
async def test_metrics_increment(daos):
    _, m = daos
    await m.increment(date_iso="2026-04-25", name="scrape_ok", dimensions="source=finnhub", delta=5)
    await m.increment(date_iso="2026-04-25", name="scrape_ok", dimensions="source=finnhub", delta=3)
    val = await m.get(date_iso="2026-04-25", name="scrape_ok", dimensions="source=finnhub")
    assert val == 8.0
