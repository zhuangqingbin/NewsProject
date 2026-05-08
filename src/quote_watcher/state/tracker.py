"""StateTracker: regroup cooldown checks around AlertStateDAO."""
from __future__ import annotations

import time
from collections.abc import Callable

from quote_watcher.storage.dao.alert_state import AlertStateDAO


class StateTracker:
    def __init__(
        self,
        *,
        dao: AlertStateDAO,
        now_fn: Callable[[], int] | None = None,
    ) -> None:
        self._dao = dao
        self._now = now_fn or (lambda: int(time.time()))

    async def is_in_cooldown(
        self, rule_id: str, ticker: str, cooldown_min: int
    ) -> bool:
        state = await self._dao.get(rule_id, ticker)
        if state is None:
            return False
        return (self._now() - state.last_triggered_at) < cooldown_min * 60

    async def mark_triggered(
        self, rule_id: str, ticker: str, *, value: float | None
    ) -> None:
        await self._dao.upsert(
            rule_id=rule_id, ticker=ticker,
            last_triggered_at=self._now(), last_value=value,
        )

    async def bump_count(self, rule_id: str, ticker: str) -> None:
        await self._dao.bump(rule_id=rule_id, ticker=ticker)
