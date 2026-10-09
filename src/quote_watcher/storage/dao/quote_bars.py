"""DAO for quote_bars_daily / quote_bars_1min."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.storage.models import QuoteBarDaily


class QuoteBarsDailyDAO:
    def __init__(self, db: QuoteDatabase) -> None:
        self._db = db

    async def list_recent(
        self, ticker: str, days: int, *, through: date | None = None
    ) -> list[QuoteBarDaily]:
        """Latest `days` bars for ticker, sorted by trade_date ASC."""
        async with self._db.session() as sess:
            query = select(QuoteBarDaily).where(QuoteBarDaily.ticker == ticker)
            if through is not None:
                query = query.where(QuoteBarDaily.trade_date <= through)
            result = await sess.execute(query.order_by(QuoteBarDaily.trade_date.desc()).limit(days))
            rows = list(result.scalars().all())
            rows.reverse()
            return rows

    async def upsert_many(
        self,
        ticker: str,
        bars: list[tuple[date, float, float, float, float, float, int, float]],
        *,
        volume_shares: dict[date, int] | None = None,
    ) -> None:
        """bars: (trade_date, open, high, low, close, prev_close, volume, amount)."""
        if not bars:
            return
        async with self._db.session() as sess:
            for d, o, h, low, c, pc, vol, amt in bars:
                existing = (
                    await sess.execute(
                        select(QuoteBarDaily).where(
                            QuoteBarDaily.ticker == ticker,
                            QuoteBarDaily.trade_date == d,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    sess.add(
                        QuoteBarDaily(
                            ticker=ticker,
                            trade_date=d,
                            open=o,
                            high=h,
                            low=low,
                            close=c,
                            prev_close=pc,
                            volume=vol,
                            volume_shares=volume_shares.get(d)
                            if volume_shares is not None
                            else None,
                            amount=amt,
                        )
                    )
                else:
                    existing.open = o
                    existing.high = h
                    existing.low = low
                    existing.close = c
                    existing.prev_close = pc
                    existing.volume = vol
                    existing.volume_shares = (
                        volume_shares.get(d) if volume_shares is not None else None
                    )
                    existing.amount = amt
            await sess.commit()
