from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import RawNews


class RawNewsDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        *,
        source: str,
        market: str,
        url: str,
        url_hash: str,
        title: str,
        title_simhash: int,
        body: str | None,
        raw_meta: dict[str, Any],
        fetched_at_iso: str,
        published_at_iso: str,
        status: str = "pending",
    ) -> int:
        row = RawNews(
            source=source,
            market=market,
            url=url,
            url_hash=url_hash,
            title=title,
            title_simhash=title_simhash,
            body=body,
            raw_meta=raw_meta,
            fetched_at=datetime.fromisoformat(fetched_at_iso),
            published_at=datetime.fromisoformat(published_at_iso),
            status=status,
        )
        async with self._db.session() as s:
            try:
                s.add(row)
                await s.commit()
                await s.refresh(row)
            except IntegrityError:
                await s.rollback()
                existing = await self.find_by_url_hash(url_hash)
                assert existing is not None and existing.id is not None
                return existing.id
        assert row.id is not None
        return row.id

    async def get(self, raw_id: int) -> RawNews | None:
        async with self._db.session() as s:
            return await s.get(RawNews, raw_id)

    async def find_by_url_hash(self, url_hash: str) -> RawNews | None:
        async with self._db.session() as s:
            res = await s.execute(select(RawNews).where(RawNews.url_hash == url_hash))
            return res.scalar_one_or_none()

    async def list_pending(self, limit: int = 100) -> list[RawNews]:
        async with self._db.session() as s:
            res = await s.execute(
                select(RawNews)
                .where(RawNews.status == "pending")
                .order_by(RawNews.published_at)
                .limit(limit)
            )
            return list(res.scalars())

    async def mark_status(self, raw_id: int, status: str, error: str | None = None) -> None:
        async with self._db.session() as s:
            row = await s.get(RawNews, raw_id)
            if row is None:
                return
            row.status = status
            row.error = error
            await s.commit()

    async def list_recent_simhashes(
        self,
        window_hours: int = 24,
    ) -> list[tuple[int, int]]:
        cutoff = utc_now() - timedelta(hours=window_hours)
        async with self._db.session() as s:
            res = await s.execute(
                select(RawNews.id, RawNews.title_simhash).where(
                    RawNews.fetched_at >= cutoff.replace(tzinfo=None)
                )
            )
            return [(r[0], r[1]) for r in res.all()]
