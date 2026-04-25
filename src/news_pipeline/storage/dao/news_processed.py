from datetime import datetime

from sqlalchemy import select

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import NewsProcessed


class NewsProcessedDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        *,
        raw_id: int,
        summary: str,
        event_type: str,
        sentiment: str,
        magnitude: str,
        confidence: float,
        key_quotes: list[str],
        score: float,
        is_critical: bool,
        rule_hits: list[str],
        llm_reason: str | None,
        model_used: str,
        extracted_at: datetime,
    ) -> int:
        row = NewsProcessed(
            raw_id=raw_id,
            summary=summary,
            event_type=event_type,
            sentiment=sentiment,
            magnitude=magnitude,
            confidence=confidence,
            key_quotes=key_quotes,
            score=score,
            is_critical=is_critical,
            rule_hits=rule_hits,
            llm_reason=llm_reason,
            model_used=model_used,
            extracted_at=extracted_at,
        )
        async with self._db.session() as s:
            s.add(row)
            await s.commit()
            await s.refresh(row)
        assert row.id is not None
        return row.id

    async def get(self, news_id: int) -> NewsProcessed | None:
        async with self._db.session() as s:
            return await s.get(NewsProcessed, news_id)

    async def mark_push_status(self, news_id: int, status: str) -> None:
        async with self._db.session() as s:
            row = await s.get(NewsProcessed, news_id)
            if row is None:
                return
            row.push_status = status
            await s.commit()

    async def list_pending_push(self, limit: int = 100) -> list[NewsProcessed]:
        async with self._db.session() as s:
            res = await s.execute(
                select(NewsProcessed)
                .where(NewsProcessed.push_status == "pending")
                .order_by(NewsProcessed.extracted_at)
                .limit(limit)
            )
            return list(res.scalars())

    async def list_recent_for_ticker(self, ticker: str, limit: int = 10) -> list[NewsProcessed]:
        from news_pipeline.storage.models import Entity, NewsEntity

        async with self._db.session() as s:
            res = await s.execute(
                select(NewsProcessed)
                .join(NewsEntity, NewsEntity.news_id == NewsProcessed.id)
                .join(Entity, Entity.id == NewsEntity.entity_id)
                .where(Entity.ticker == ticker)
                .order_by(NewsProcessed.extracted_at.desc())
                .limit(limit)
            )
            return list(res.scalars())
