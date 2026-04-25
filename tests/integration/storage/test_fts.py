import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from news_pipeline.storage.db import Database


@pytest.mark.asyncio
async def test_fts_search(tmp_path):
    dsn = f"sqlite+aiosqlite:///{tmp_path}/t.db"

    # Run migrations in a thread to avoid "asyncio.run() in running loop" error
    def _run_migrations() -> None:
        from alembic import command
        from alembic.config import Config

        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", dsn)
        command.upgrade(cfg, "head")

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        await loop.run_in_executor(pool, _run_migrations)

    db = Database(dsn)
    await db.initialize()
    async with db.session() as s:
        await s.execute(
            text("""
            INSERT INTO raw_news (id, source, market, url, url_hash, title, title_simhash,
                                   fetched_at, published_at, status)
            VALUES (1, 'x', 'us', 'https://x', 'h1', 'NVDA news', 0,
                    '2026-04-25', '2026-04-25', 'processed')
        """)
        )
        await s.execute(
            text("""
            INSERT INTO news_processed
            (id, raw_id, summary, event_type, sentiment, magnitude, confidence,
             score, is_critical, model_used, extracted_at, push_status)
            VALUES (1, 1, 'NVDA exports halted', 'policy', 'bearish', 'high', 0.9,
                    80, 1, 'haiku', '2026-04-25', 'pending')
        """)
        )
        await s.commit()
        rows = (
            await s.execute(text("SELECT rowid FROM news_fts WHERE news_fts MATCH 'exports'"))
        ).all()
        assert len(rows) == 1
    await db.close()
