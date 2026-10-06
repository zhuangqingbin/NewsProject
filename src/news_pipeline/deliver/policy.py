"""Pure event decision and market routing policy."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from news_pipeline.config.schema import PushCfg
from news_pipeline.storage.models import Event
from shared.common.timeutil import ensure_utc

PolicyCfg = PushCfg


@dataclass(frozen=True)
class Decision:
    action: Literal["push", "digest", "drop"]
    reason: str
    same_as_event_id: int | None = None


def _quiet(now: datetime, cfg: PolicyCfg) -> bool:
    quiet = cfg.quiet_hours
    if not quiet.enabled:
        return False
    local = ensure_utc(now).astimezone(ZoneInfo(quiet.tz)).time().replace(tzinfo=None)
    start, end = time.fromisoformat(quiet.start), time.fromisoformat(quiet.end)
    return start <= local < end if start <= end else local >= start or local < end


def _too_old(ev: Event, now: datetime, cfg: PolicyCfg) -> bool:
    return ensure_utc(now) - ensure_utc(ev.first_seen_at) > timedelta(minutes=cfg.max_age_min)


def _from_rules(ev: Event, now: datetime, cfg: PolicyCfg) -> Decision:
    if ev.rule_decision == "push":
        if not ev.first_party and _too_old(ev, now, cfg):
            return Decision("digest", "stale")
        if _quiet(now, cfg) and ev.rule_reason not in cfg.quiet_hours.allow_reasons:
            return Decision("digest", "quiet_hours")
        return Decision("push", ev.rule_reason or "rules")
    if ev.rule_decision in {"digest_hi", "digest_lo"}:
        return Decision("digest", ev.rule_reason or "rules")
    return Decision("drop", ev.rule_reason or "rules")


def decide(ev: Event, now: datetime, cfg: PolicyCfg) -> Decision:
    if ev.assess_status != "done":
        return _from_rules(ev, now, cfg)
    if ev.novelty == "repeat" and ev.same_as_event_id:
        return Decision("drop", "repeat", ev.same_as_event_id)
    materiality = ev.materiality or 1
    if ev.first_party:
        materiality = max(materiality, cfg.first_party_floor.get(ev.rule_reason, 1))
    direct = any(
        holding.get("relation") in {"subject", "counterparty"} for holding in ev.holdings or []
    )
    market_wide = ev.scope in {"market", "sector"} and materiality >= cfg.push_min_materiality_macro
    if (
        materiality >= cfg.push_min_materiality
        and (direct or market_wide)
        and (ev.confidence or 0) >= cfg.min_confidence
    ):
        if not ev.first_party and _too_old(ev, now, cfg):
            return Decision("digest", "stale")
        if _quiet(now, cfg) and materiality < cfg.quiet_min_materiality:
            return Decision("digest", "quiet_hours")
        return Decision("push", f"materiality={materiality}")
    if materiality >= cfg.digest_min_materiality:
        return Decision("digest", f"materiality={materiality}")
    if ev.rule_decision == "push":
        return Decision("digest", "rule_llm_disagree")
    return Decision("drop", f"materiality={materiality}")


def markets_for_event(ev: Event, ticker_market: Mapping[str, str]) -> list[str]:
    direct_markets = {
        ticker_market[holding["ticker"]]
        for holding in ev.holdings or []
        if holding.get("relation") in {"subject", "counterparty"}
        and holding.get("ticker") in ticker_market
    }
    return sorted(direct_markets or set(ev.markets))
