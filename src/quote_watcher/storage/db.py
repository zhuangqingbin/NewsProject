"""QuoteDatabase: async SQLAlchemy wrapper for data/quotes.db."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from quote_watcher.storage.models import Base


class QuoteDatabase:
    def __init__(self, url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(url, echo=False, future=True)
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            columns = await conn.run_sync(
                lambda sync: {c["name"] for c in inspect(sync).get_columns("quote_bars_daily")}
            )
            if "volume_shares" not in columns:
                await conn.exec_driver_sql(
                    "ALTER TABLE quote_bars_daily ADD COLUMN volume_shares BIGINT"
                )

    def session(self) -> AsyncSession:
        return self._sessionmaker()

    async def close(self) -> None:
        await self._engine.dispose()
