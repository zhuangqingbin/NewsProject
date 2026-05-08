"""AlertEngine: evaluate alert rules against a QuoteSnapshot."""
from __future__ import annotations

import asteval

from quote_watcher.alerts.context import build_threshold_context
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.alerts.verdict import AlertVerdict
from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.state.tracker import StateTracker
from shared.observability.log import get_logger

log = get_logger(__name__)


class AlertEngine:
    def __init__(self, *, rules: list[AlertRule], tracker: StateTracker) -> None:
        self._rules = rules
        self._tracker = tracker

    async def evaluate_for_snapshot(
        self,
        snap: QuoteSnapshot,
        *,
        volume_avg5d: float = 0.0,
        volume_avg20d: float = 0.0,
        price_high_today_yday: float = 0.0,
        price_low_today_yday: float = 0.0,
    ) -> list[AlertVerdict]:
        applicable = [
            r for r in self._rules
            if r.kind == AlertKind.THRESHOLD and r.ticker == snap.ticker
        ]
        if not applicable:
            return []
        ctx = build_threshold_context(
            snap,
            volume_avg5d=volume_avg5d,
            volume_avg20d=volume_avg20d,
            price_high_today_yday=price_high_today_yday,
            price_low_today_yday=price_low_today_yday,
        )
        out: list[AlertVerdict] = []
        for rule in applicable:
            interp = asteval.Interpreter(usersyms=ctx, no_print=True, no_assert=True)
            try:
                result = bool(interp(rule.expr))
            except Exception as e:
                log.warning("rule_eval_failed", rule=rule.id, error=str(e))
                continue
            if interp.error:
                log.warning(
                    "rule_eval_runtime_error",
                    rule=rule.id,
                    errors=[str(e.get_error()) for e in interp.error],
                )
                continue
            if not result:
                continue
            if await self._tracker.is_in_cooldown(rule.id, snap.ticker, rule.cooldown_min):
                await self._tracker.bump_count(rule.id, snap.ticker)
                continue
            await self._tracker.mark_triggered(
                rule.id, snap.ticker, value=ctx.get("price_now"),
            )
            out.append(AlertVerdict(rule=rule, snapshot=snap, ctx_dump=dict(ctx)))
        return out
