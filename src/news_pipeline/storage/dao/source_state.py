from datetime import datetime, timedelta

from sqlalchemy import select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import SourceState
from shared.common.timeutil import ensure_utc


class SourceStateDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, source: str) -> SourceState | None:
        async with self._db.session() as s:
            return await s.get(SourceState, source)

    async def list_all(self) -> list[SourceState]:
        async with self._db.session() as session:
            return list((await session.execute(select(SourceState))).scalars())

    async def record_success(
        self, source: str, *, new_items: int, now: datetime | None = None
    ) -> None:
        at = ensure_utc(now or utc_now()).replace(tzinfo=None)
        async with self._db.session() as session:
            row = await session.get(SourceState, source)
            if row is None:
                row = SourceState(source=source)
                session.add(row)
            if row.first_success_at is None:
                row.first_success_at = at
            row.last_success_at = at
            row.last_fetched_at = at
            if new_items:
                row.last_item_at = at
            row.consecutive_failures = 0
            row.error_count = 0
            row.last_error = None
            row.paused_until = None
            await session.commit()

    async def record_failure(
        self,
        source: str,
        *,
        error: str,
        base_interval: int,
        structural: bool = False,
        now: datetime | None = None,
    ) -> None:
        at = ensure_utc(now or utc_now()).replace(tzinfo=None)
        async with self._db.session() as session:
            row = await session.get(SourceState, source)
            if row is None:
                row = SourceState(source=source)
                session.add(row)
            row.consecutive_failures += 1
            row.error_count += 1
            row.last_error = ("structural: " if structural else "") + error
            delay = min(base_interval * 2 ** min(row.consecutive_failures - 1, 16), 1800)
            row.paused_until = at + timedelta(seconds=delay)
            await session.commit()

    async def transition_health(
        self, source: str, *, health: str, reason: str, now: datetime
    ) -> bool:
        async with self._db.session() as session:
            row = await session.get(SourceState, source)
            if row is None or row.health == health:
                if row is not None and row.health_reason != reason:
                    row.health_reason = reason
                    await session.commit()
                return False
            row.health = health
            row.health_reason = reason
            row.health_changed_at = ensure_utc(now).replace(tzinfo=None)
            await session.commit()
            return True

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
