from collections.abc import Sequence

from sqlalchemy import select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import DigestBuffer


class DigestBufferDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def enqueue(self, *, news_id: int, market: str, scheduled_digest: str) -> int:
        row = DigestBuffer(
            news_id=news_id,
            market=market,
            scheduled_digest=scheduled_digest,
            added_at=utc_now().replace(tzinfo=None),
        )
        async with self._db.session() as s:
            s.add(row)
            await s.commit()
            await s.refresh(row)
        assert row.id is not None
        return row.id

    async def list_pending(self, scheduled_digest: str) -> list[DigestBuffer]:
        async with self._db.session() as s:
            res = await s.execute(
                select(DigestBuffer)
                .where(
                    DigestBuffer.scheduled_digest == scheduled_digest,
                    DigestBuffer.consumed_at.is_(None),
                )
                .order_by(DigestBuffer.added_at)
            )
            return list(res.scalars())

    async def mark_consumed(self, ids: Sequence[int]) -> None:
        async with self._db.session() as s:
            for i in ids:
                row = await s.get(DigestBuffer, i)
                if row is not None:
                    row.consumed_at = utc_now().replace(tzinfo=None)
            await s.commit()
