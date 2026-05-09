"""AlertEngine: evaluate alert rules against a QuoteSnapshot or portfolio."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import asteval

from news_pipeline.config.schema import HoldingsFile
from quote_watcher.alerts.context import (
    build_composite_holding_context,
    build_composite_portfolio_context,
    build_indicator_context,
    build_threshold_context,
)
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.alerts.verdict import AlertVerdict
from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.state.tracker import StateTracker
from shared.observability.log import get_logger

if TYPE_CHECKING:
    from quote_watcher.store.kline import DailyKlineCache

log = get_logger(__name__)

_PORTFOLIO_TICKER_KEY = "_portfolio"


class AlertEngine:
    def __init__(
        self,
        *,
        rules: list[AlertRule],
        tracker: StateTracker,
        holdings: HoldingsFile | None = None,
        kline_cache: DailyKlineCache | None = None,
    ) -> None:
        self._rules = rules
        self._tracker = tracker
        self._holdings = holdings or HoldingsFile()
        self._holdings_by_ticker = {h.ticker: h for h in self._holdings.holdings}
        self._kline_cache = kline_cache

    async def evaluate_for_snapshot(
        self,
        snap: QuoteSnapshot,
        *,
        volume_avg5d: float = 0.0,
        volume_avg20d: float = 0.0,
        price_high_today_yday: float = 0.0,
        price_low_today_yday: float = 0.0,
    ) -> list[AlertVerdict]:
        out: list[AlertVerdict] = []

        # 1) threshold rules for this ticker
        threshold_rules = [
            r for r in self._rules
            if r.kind == AlertKind.THRESHOLD and r.ticker == snap.ticker
        ]
        if threshold_rules:
            ctx = build_threshold_context(
                snap,
                volume_avg5d=volume_avg5d,
                volume_avg20d=volume_avg20d,
                price_high_today_yday=price_high_today_yday,
                price_low_today_yday=price_low_today_yday,
            )
            out += await self._run_rules(threshold_rules, snap, ctx)

        # 2) composite holding rules for this ticker
        composite_holding_rules = [
            r for r in self._rules
            if r.kind == AlertKind.COMPOSITE and r.holding == snap.ticker
        ]
        if composite_holding_rules:
            holding = self._holdings_by_ticker.get(snap.ticker)
            if holding is None:
                log.warning("composite_rule_holding_missing", ticker=snap.ticker)
            else:
                ctx = build_composite_holding_context(
                    snap, holding,
                    volume_avg5d=volume_avg5d, volume_avg20d=volume_avg20d,
                )
                out += await self._run_rules(composite_holding_rules, snap, ctx)

        # 3) indicator rules for this ticker
        indicator_rules = [
            r for r in self._rules
            if r.kind == AlertKind.INDICATOR and r.ticker == snap.ticker
        ]
        if indicator_rules:
            if self._kline_cache is None:
                log.warning(
                    "indicator_rule_skipped_no_kline_cache",
                    ticker=snap.ticker,
                    rules=[r.id for r in indicator_rules],
                )
            else:
                bars = await self._kline_cache.get_cached(snap.ticker, days=250)
                ctx = build_indicator_context(
                    snap, bars=bars,
                    volume_avg5d=volume_avg5d, volume_avg20d=volume_avg20d,
                )
                out += await self._run_rules(indicator_rules, snap, ctx)

        # 4) event rules with target_kind=ticker (limit_up/down etc)
        event_ticker_rules = [
            r for r in self._rules
            if r.kind == AlertKind.EVENT
            and r.target_kind == "ticker"
            and r.ticker == snap.ticker
        ]
        if event_ticker_rules:
            ctx = build_threshold_context(
                snap,
                volume_avg5d=volume_avg5d,
                volume_avg20d=volume_avg20d,
                price_high_today_yday=price_high_today_yday,
                price_low_today_yday=price_low_today_yday,
            )
            out += await self._run_rules(event_ticker_rules, snap, ctx)

        return out

    async def evaluate_portfolio(
        self, *, snaps_by_ticker: dict[str, QuoteSnapshot],
    ) -> list[AlertVerdict]:
        portfolio_rules = [
            r for r in self._rules
            if r.kind == AlertKind.COMPOSITE and r.portfolio
        ]
        if not portfolio_rules:
            return []
        any_snap = next(iter(snaps_by_ticker.values()), None)
        if any_snap is None:
            return []
        ctx = build_composite_portfolio_context(self._holdings, snaps_by_ticker)
        out: list[AlertVerdict] = []
        for rule in portfolio_rules:
            if not self._eval_expr(rule, ctx):
                continue
            if await self._tracker.is_in_cooldown(
                rule.id, _PORTFOLIO_TICKER_KEY, rule.cooldown_min
            ):
                await self._tracker.bump_count(rule.id, _PORTFOLIO_TICKER_KEY)
                continue
            await self._tracker.mark_triggered(
                rule.id, _PORTFOLIO_TICKER_KEY,
                value=ctx.get("total_unrealized_pnl_pct"),
            )
            out.append(AlertVerdict(rule=rule, snapshot=any_snap, ctx_dump=dict(ctx)))
        return out

    async def _run_rules(
        self,
        rules: list[AlertRule],
        snap: QuoteSnapshot,
        ctx: dict[str, Any],
    ) -> list[AlertVerdict]:
        out: list[AlertVerdict] = []
        for rule in rules:
            if not self._eval_expr(rule, ctx):
                continue
            if await self._tracker.is_in_cooldown(
                rule.id, snap.ticker, rule.cooldown_min
            ):
                await self._tracker.bump_count(rule.id, snap.ticker)
                continue
            await self._tracker.mark_triggered(
                rule.id, snap.ticker, value=ctx.get("price_now"),
            )
            out.append(AlertVerdict(rule=rule, snapshot=snap, ctx_dump=dict(ctx)))
        return out

    def _eval_expr(self, rule: AlertRule, ctx: dict[str, Any]) -> bool:
        interp = asteval.Interpreter(usersyms=ctx, no_print=True, no_assert=True)
        try:
            result = bool(interp(rule.expr))
        except Exception as e:
            log.warning("rule_eval_failed", rule=rule.id, error=str(e))
            return False
        if interp.error:
            log.warning(
                "rule_eval_runtime_error",
                rule=rule.id,
                errors=[str(e.get_error()) for e in interp.error],
            )
            return False
        return result
