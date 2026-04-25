from datetime import timedelta

from sqlalchemy import select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import ChartCache


class ChartCacheDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, request_hash: str) -> ChartCache | None:
        async with self._db.session() as s:
            res = await s.execute(
                select(ChartCache).where(ChartCache.request_hash == request_hash)
            )
            row = res.scalar_one_or_none()
            if row is None:
                return None
            if row.expires_at < utc_now().replace(tzinfo=None):
                return None
            return row

    async def put(
        self,
        *,
        request_hash: str,
        ticker: str,
        kind: str,
        oss_url: str,
        ttl_days: int = 30,
    ) -> int:
        now = utc_now().replace(tzinfo=None)
        row = ChartCache(
            request_hash=request_hash,
            ticker=ticker,
            kind=kind,
            oss_url=oss_url,
            generated_at=now,
            expires_at=now + timedelta(days=ttl_days),
        )
        async with self._db.session() as s:
            s.add(row)
            await s.commit()
            await s.refresh(row)
        assert row.id is not None
        return row.id
