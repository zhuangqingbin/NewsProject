"""DAO for the alert_state table (cooldown tracking)."""
from __future__ import annotations

from sqlalchemy import select

from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.storage.models import AlertState


class AlertStateDAO:
    def __init__(self, db: QuoteDatabase) -> None:
        self._db = db

    async def get(self, rule_id: str, ticker: str) -> AlertState | None:
        async with self._db.session() as sess:
            result = await sess.execute(
                select(AlertState).where(
                    AlertState.rule_id == rule_id,
                    AlertState.ticker == ticker,
                )
            )
            return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        rule_id: str,
        ticker: str,
        last_triggered_at: int,
        last_value: float | None,
    ) -> None:
        async with self._db.session() as sess:
            existing = (
                await sess.execute(
                    select(AlertState).where(
                        AlertState.rule_id == rule_id,
                        AlertState.ticker == ticker,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                sess.add(AlertState(
                    rule_id=rule_id, ticker=ticker,
                    last_triggered_at=last_triggered_at,
                    last_value=last_value,
                    trigger_count_today=1,
                ))
            else:
                existing.last_triggered_at = last_triggered_at
                existing.last_value = last_value
                existing.trigger_count_today += 1
            await sess.commit()

    async def bump(self, *, rule_id: str, ticker: str) -> None:
        async with self._db.session() as sess:
            existing = (
                await sess.execute(
                    select(AlertState).where(
                        AlertState.rule_id == rule_id,
                        AlertState.ticker == ticker,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.trigger_count_today += 1
                await sess.commit()
