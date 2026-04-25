from datetime import timedelta

from sqlalchemy import func, select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import PushLog


class PushLogDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def write(
        self,
        *,
        news_id: int,
        channel: str,
        status: str,
        http_status: int | None = None,
        response: str = "",
        retries: int = 0,
    ) -> None:
        async with self._db.session() as s:
            row = PushLog(
                news_id=news_id,
                channel=channel,
                sent_at=utc_now().replace(tzinfo=None),
                status=status,
                http_status=http_status,
                response=response,
                retries=retries,
            )
            s.add(row)
            await s.commit()

    async def count_today_failures(self, channel: str) -> int:
        cutoff = (utc_now() - timedelta(days=1)).replace(tzinfo=None)
        async with self._db.session() as s:
            res = await s.execute(
                select(func.count()).where(
                    PushLog.channel == channel,
                    PushLog.status == "failed",
                    PushLog.sent_at >= cutoff,
                )
            )
            return int(res.scalar() or 0)

    async def failure_counts_by_channel(self, window_minutes: int = 60) -> dict[str, int]:
        """Return failure counts per channel in the last window_minutes.

        Used by C-4 push failure alert job.
        """
        cutoff = (utc_now() - timedelta(minutes=window_minutes)).replace(tzinfo=None)
        async with self._db.session() as s:
            res = await s.execute(
                select(PushLog.channel, func.count().label("cnt"))
                .where(
                    PushLog.status == "failed",
                    PushLog.sent_at >= cutoff,
                )
                .group_by(PushLog.channel)
            )
            return {row.channel: int(row.cnt) for row in res}
