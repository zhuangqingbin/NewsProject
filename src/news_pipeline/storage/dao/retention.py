"""Retention for v2 tables while preserving referenced legacy history."""

from datetime import datetime, timedelta

from sqlalchemy import text

from news_pipeline.storage.db import Database
from shared.common.timeutil import ensure_utc, utc_now


class RetentionDAO:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def prune(self, *, now: datetime | None = None) -> dict[str, int]:
        at = ensure_utc(now or utc_now()).replace(tzinfo=None)
        params = {
            f"days{days}": (at - timedelta(days=days)).isoformat(sep=" ", timespec="microseconds")
            for days in (30, 60, 180, 365)
        }
        queries = {
            "deliveries": """
                DELETE FROM deliveries WHERE
                    event_id IN (SELECT id FROM events WHERE first_seen_at < :days365)
                    OR created_at < :days365
                    OR (status='shadow' AND created_at < :days30)
            """,
            "event_articles": """
                DELETE FROM event_articles WHERE event_id IN
                    (SELECT id FROM events WHERE first_seen_at < :days365)
            """,
            "events": "DELETE FROM events WHERE first_seen_at < :days365",
            "raw_news": """
                DELETE FROM raw_news WHERE
                    NOT EXISTS (SELECT 1 FROM event_articles WHERE raw_id=raw_news.id)
                    AND NOT EXISTS (SELECT 1 FROM news_processed WHERE raw_id=raw_news.id)
                    AND (fetched_at < :days365 OR
                         ((v2_state IN ('skipped_rules','skipped_low') OR
                           status IN ('skipped_rules','skipped_low','duplicate','seeded'))
                          AND fetched_at < :days60))
            """,
            "llm_calls": "DELETE FROM llm_calls WHERE created_at < :days180",
        }
        counts: dict[str, int] = {}
        async with self.db.session() as session:
            for table, query in queries.items():
                await session.execute(text(query), params)
                result = await session.execute(text("SELECT changes()"))
                counts[table] = int(result.scalar_one())
            await session.commit()
        return counts

    async def vacuum(self) -> None:
        """VACUUM must use its own connection outside any transaction."""
        async with self.db.engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text("VACUUM"))
