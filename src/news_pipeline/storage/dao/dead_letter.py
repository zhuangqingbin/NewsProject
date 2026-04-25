from sqlalchemy import select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import DeadLetter


class DeadLetterDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        *,
        kind: str,
        payload: str,
        error: str,
        retries: int = 0,
    ) -> int:
        row = DeadLetter(
            kind=kind,
            payload=payload,
            error=error,
            retries=retries,
            created_at=utc_now().replace(tzinfo=None),
        )
        async with self._db.session() as s:
            s.add(row)
            await s.commit()
            await s.refresh(row)
        assert row.id is not None
        return row.id

    async def list_unresolved(self, kind: str | None = None) -> list[DeadLetter]:
        async with self._db.session() as s:
            stmt = select(DeadLetter).where(DeadLetter.resolved_at.is_(None))
            if kind is not None:
                stmt = stmt.where(DeadLetter.kind == kind)
            res = await s.execute(stmt)
            return list(res.scalars())

    async def mark_resolved(self, dlq_id: int) -> None:
        async with self._db.session() as s:
            row = await s.get(DeadLetter, dlq_id)
            if row is None:
                return
            row.resolved_at = utc_now().replace(tzinfo=None)
            await s.commit()
