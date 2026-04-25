from typing import Any

from sqlalchemy import select

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import Entity, NewsEntity


class EntitiesDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(
        self,
        *,
        type: str,
        name: str,
        ticker: str | None = None,
        market: str | None = None,
        aliases: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        async with self._db.session() as s:
            res = await s.execute(select(Entity).where(Entity.type == type, Entity.name == name))
            existing = res.scalar_one_or_none()
            if existing is not None:
                # merge aliases
                if aliases:
                    merged = list({*(existing.aliases or []), *aliases})
                    existing.aliases = merged
                if ticker and not existing.ticker:
                    existing.ticker = ticker
                if market and not existing.market:
                    existing.market = market
                await s.commit()
                assert existing.id is not None
                return existing.id
            row = Entity(
                type=type,
                name=name,
                ticker=ticker,
                market=market,
                aliases=aliases,
                metadata_=metadata,
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
            assert row.id is not None
            return row.id

    async def find(self, *, type: str, name: str) -> Entity | None:
        async with self._db.session() as s:
            res = await s.execute(select(Entity).where(Entity.type == type, Entity.name == name))
            return res.scalar_one_or_none()

    async def find_by_ticker(self, ticker: str) -> Entity | None:
        async with self._db.session() as s:
            res = await s.execute(select(Entity).where(Entity.ticker == ticker))
            return res.scalar_one_or_none()

    async def link_news(
        self,
        *,
        news_id: int,
        entity_id: int,
        role: str,
        salience: float,
    ) -> None:
        async with self._db.session() as s:
            row = NewsEntity(news_id=news_id, entity_id=entity_id, role=role, salience=salience)
            s.add(row)
            await s.commit()
