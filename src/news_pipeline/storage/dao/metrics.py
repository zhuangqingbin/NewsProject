from sqlalchemy import select

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import DailyMetric


class MetricsDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def increment(
        self,
        *,
        date_iso: str,
        name: str,
        dimensions: str = "",
        delta: float = 1.0,
    ) -> None:
        async with self._db.session() as s:
            res = await s.execute(
                select(DailyMetric).where(
                    DailyMetric.metric_date == date_iso,
                    DailyMetric.metric_name == name,
                    DailyMetric.dimensions == dimensions,
                )
            )
            row = res.scalar_one_or_none()
            if row is None:
                row = DailyMetric(
                    metric_date=date_iso,
                    metric_name=name,
                    dimensions=dimensions,
                    metric_value=0.0,
                )
                s.add(row)
            row.metric_value += delta
            await s.commit()

    async def get(
        self,
        *,
        date_iso: str,
        name: str,
        dimensions: str = "",
    ) -> float | None:
        async with self._db.session() as s:
            res = await s.execute(
                select(DailyMetric.metric_value).where(
                    DailyMetric.metric_date == date_iso,
                    DailyMetric.metric_name == name,
                    DailyMetric.dimensions == dimensions,
                )
            )
            v = res.scalar_one_or_none()
            return float(v) if v is not None else None
