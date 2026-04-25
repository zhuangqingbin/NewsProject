from datetime import datetime, timedelta

import pytest

from news_pipeline.storage.dao.audit_log import AuditLogDAO
from news_pipeline.storage.dao.dead_letter import DeadLetterDAO
from news_pipeline.storage.dao.push_log import PushLogDAO
from news_pipeline.storage.dao.source_state import SourceStateDAO
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import SQLModelBase


@pytest.fixture
async def daos(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as c:
        await c.run_sync(SQLModelBase.metadata.create_all)
    yield (SourceStateDAO(db), PushLogDAO(db), AuditLogDAO(db), DeadLetterDAO(db))
    await db.close()


@pytest.mark.asyncio
async def test_source_state_pause(daos):
    src, _, _, _ = daos
    until = datetime.utcnow() + timedelta(minutes=30)
    await src.set_paused("xueqiu", until=until, error="anti_crawl")
    assert await src.is_paused("xueqiu") is True


@pytest.mark.asyncio
async def test_dlq_insert_and_list_unresolved(daos):
    _, _, _, dlq = daos
    await dlq.insert(kind="scrape", payload="{}", error="x", retries=0)
    items = await dlq.list_unresolved()
    assert len(items) == 1


@pytest.mark.asyncio
async def test_audit_log_writes(daos):
    _, _, audit, _ = daos
    await audit.write(action="config_reload", actor="system", detail="ok")
    rows = await audit.recent(limit=5)
    assert rows[0].action == "config_reload"


@pytest.mark.asyncio
async def test_push_log_writes(daos):
    _src, plog, _, _ = daos
    # push_log.news_id FK → news_processed; insert prerequisite rows via raw SQL
    from sqlalchemy import text

    async with plog._db.session() as s:
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
    await plog.write(
        news_id=1, channel="tg_us", status="ok", http_status=200, response="", retries=0
    )
    cnt = await plog.count_today_failures("tg_us")
    assert cnt == 0
