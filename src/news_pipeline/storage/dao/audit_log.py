from sqlalchemy import select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import AuditLog


class AuditLogDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def write(
        self,
        *,
        action: str,
        actor: str | None = None,
        detail: str | None = None,
    ) -> None:
        async with self._db.session() as s:
            row = AuditLog(
                action=action,
                actor=actor,
                detail=detail,
                created_at=utc_now().replace(tzinfo=None),
            )
            s.add(row)
            await s.commit()

    async def recent(self, limit: int = 20) -> list[AuditLog]:
        async with self._db.session() as s:
            res = await s.execute(
                select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
            )
            return list(res.scalars())
