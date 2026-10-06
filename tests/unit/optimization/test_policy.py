from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest

from news_pipeline.config.schema import PushCfg, QuietHoursCfg
from news_pipeline.storage.models import Event

NOW = datetime(2026, 10, 6, 10, tzinfo=UTC)


def event(**values):
    return Event(
        first_seen_at=NOW.replace(tzinfo=None),
        last_seen_at=NOW.replace(tzinfo=None),
        headline="公司发布重大进展",
        **values,
    )


def decide(ev, now=NOW, cfg=None):
    return import_module("news_pipeline.deliver.policy").decide(ev, now, cfg or PushCfg())


@pytest.mark.parametrize(
    "materiality,direct,scope,confidence,action",
    [
        (4, True, "company", 0.5, "push"),
        (5, True, "company", 0.9, "push"),
        (4, True, "company", 0.49, "digest"),
        (3, True, "company", 0.9, "digest"),
        (2, True, "company", 0.9, "drop"),
        (1, True, "company", 0.9, "drop"),
        (4, False, "company", 0.9, "digest"),
        (4, False, "market", 0.9, "digest"),
        (5, False, "market", 0.5, "push"),
        (5, False, "sector", 0.5, "push"),
    ],
)
def test_materiality_relation_scope_and_confidence_matrix(
    materiality, direct, scope, confidence, action
):
    ev = event(
        assess_status="done",
        materiality=materiality,
        confidence=confidence,
        scope=scope,
        holdings=[{"ticker": "NVDA", "relation": "subject" if direct else "mention"}],
    )
    assert decide(ev).action == action


def test_first_party_floor_and_staleness_exemption():
    ev = event(
        assess_status="done",
        materiality=1,
        confidence=0.9,
        scope="company",
        holdings=[{"ticker": "NVDA", "relation": "counterparty"}],
        first_party=True,
        rule_reason="tier:high",
    )
    ev.first_seen_at = (NOW - timedelta(days=5)).replace(tzinfo=None)
    assert decide(ev).action == "push"
    ev.rule_reason = "tier:normal"
    assert decide(ev).action == "digest"


def test_repeat_preserves_merge_target_and_updates_can_push():
    ev = event(
        assess_status="done",
        materiality=5,
        confidence=0.9,
        scope="company",
        holdings=[{"ticker": "NVDA", "relation": "subject"}],
        novelty="repeat",
        same_as_event_id=42,
    )
    result = decide(ev)
    assert (result.action, result.reason, result.same_as_event_id) == ("drop", "repeat", 42)
    ev.novelty = "update"
    assert decide(ev).action == "push"


def test_rule_llm_disagreement_is_retained_in_digest():
    result = decide(
        event(assess_status="done", materiality=1, confidence=0.9, rule_decision="push")
    )
    assert (result.action, result.reason) == ("digest", "rule_llm_disagree")


@pytest.mark.parametrize(
    "status,rule,expected",
    [
        ("failed", "push", "push"),
        ("skipped", "digest_hi", "digest"),
        ("pending", "digest_lo", "digest"),
        ("failed", "drop", "drop"),
    ],
)
def test_non_done_assessments_use_rules(status, rule, expected):
    assert decide(event(assess_status=status, rule_decision=rule)).action == expected


def test_stale_pushes_are_downgraded_in_llm_and_rules_modes():
    for status in ("done", "failed"):
        ev = event(
            assess_status=status,
            rule_decision="push",
            materiality=5,
            confidence=0.9,
            scope="company",
            holdings=[{"ticker": "NVDA", "relation": "subject"}],
        )
        ev.first_seen_at = (NOW - timedelta(minutes=91)).replace(tzinfo=None)
        result = decide(ev)
        assert (result.action, result.reason) == ("digest", "stale")


def test_quiet_hours_materiality_floor_and_rule_allow_reasons():
    quiet = datetime(2026, 10, 5, 18, tzinfo=UTC)  # 02:00 Beijing
    cfg = PushCfg(quiet_hours=QuietHoursCfg(enabled=True))
    ev = event(
        assess_status="done",
        materiality=4,
        confidence=0.9,
        scope="company",
        holdings=[{"ticker": "NVDA", "relation": "subject"}],
    )
    ev.first_seen_at = quiet.replace(tzinfo=None)
    assert decide(ev, quiet, cfg).reason == "quiet_hours"
    ev.materiality = 5
    assert decide(ev, quiet, cfg).action == "push"
    ev.assess_status, ev.rule_decision, ev.rule_reason = "failed", "push", "big_move"
    assert decide(ev, quiet, cfg).action == "push"
    ev.rule_reason = "strong_event"
    assert decide(ev, quiet, cfg).reason == "quiet_hours"


def test_quiet_hours_can_cross_midnight_and_end_is_exclusive():
    cfg = PushCfg(quiet_hours=QuietHoursCfg(enabled=True, start="23:00", end="07:00"))
    for at, expected in [
        (datetime(2026, 10, 6, 15, tzinfo=UTC), "digest"),
        (datetime(2026, 10, 6, 23, tzinfo=UTC), "push"),
    ]:
        ev = event(assess_status="failed", rule_decision="push")
        ev.first_seen_at = at.replace(tzinfo=None)
        assert decide(ev, at, cfg).action == expected


def test_routing_uses_direct_holdings_then_market_fallback():
    policy = import_module("news_pipeline.deliver.policy")
    ev = event(
        markets=["cn", "us"],
        holdings=[
            {"ticker": "NVDA", "relation": "subject"},
            {"ticker": "TSLA", "relation": "counterparty"},
            {"ticker": "300308", "relation": "mention"},
        ],
    )
    assert policy.markets_for_event(ev, {"NVDA": "us", "TSLA": "us", "300308": "cn"}) == ["us"]
    ev.holdings = [{"ticker": "NVDA", "relation": "peer"}]
    assert policy.markets_for_event(ev, {"NVDA": "us"}) == ["cn", "us"]
    assert policy.PolicyCfg is PushCfg
