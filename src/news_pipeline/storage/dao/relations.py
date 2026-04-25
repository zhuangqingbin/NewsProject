from datetime import datetime

from sqlalchemy import or_, select

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import Relation


class RelationsDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        *,
        subject_id: int,
        predicate: str,
        object_id: int,
        source_news_id: int,
        confidence: float,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
    ) -> int:
        row = Relation(
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            source_news_id=source_news_id,
            confidence=confidence,
            valid_from=valid_from,
            valid_until=valid_until,
        )
        async with self._db.session() as s:
            s.add(row)
            await s.commit()
            await s.refresh(row)
        assert row.id is not None
        return row.id

    async def list_for_entity(self, entity_id: int) -> list[Relation]:
        async with self._db.session() as s:
            res = await s.execute(
                select(Relation).where(
                    or_(
                        Relation.subject_id == entity_id,
                        Relation.object_id == entity_id,
                    )
                )
            )
            return list(res.scalars())
