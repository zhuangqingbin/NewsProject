from datetime import datetime

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import SourceState


class SourceStateDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, source: str) -> SourceState | None:
        async with self._db.session() as s:
            return await s.get(SourceState, source)

    async def update_watermark(
        self,
        source: str,
        *,
        last_fetched_at: datetime,
        last_seen_url: str | None = None,
    ) -> None:
        async with self._db.session() as ses:
            row = await ses.get(SourceState, source)
            if row is None:
                row = SourceState(source=source)
                ses.add(row)
            row.last_fetched_at = last_fetched_at
            if last_seen_url:
                row.last_seen_url = last_seen_url
            row.last_error = None
            row.error_count = 0
            await ses.commit()

    async def record_error(self, source: str, error: str) -> None:
        async with self._db.session() as ses:
            row = await ses.get(SourceState, source)
            if row is None:
                row = SourceState(source=source)
                ses.add(row)
            row.last_error = error
            row.error_count = (row.error_count or 0) + 1
            await ses.commit()

    async def set_paused(self, source: str, *, until: datetime, error: str = "") -> None:
        async with self._db.session() as ses:
            row = await ses.get(SourceState, source)
            if row is None:
                row = SourceState(source=source)
                ses.add(row)
            row.paused_until = until
            row.last_error = error
            await ses.commit()

    async def is_paused(self, source: str) -> bool:
        row = await self.get(source)
        if row is None or row.paused_until is None:
            return False
        return row.paused_until > utc_now().replace(tzinfo=None)
