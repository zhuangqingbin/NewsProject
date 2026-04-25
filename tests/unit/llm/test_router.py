# tests/unit/llm/test_router.py
from datetime import datetime

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.llm.extractors import Tier0Verdict
from news_pipeline.llm.router import LLMRouter


def _art(source: str = "x", title: str = "t") -> RawArticle:
    return RawArticle(
        source=source,
        market=Market.US,
        fetched_at=datetime(2026, 4, 25),
        published_at=datetime(2026, 4, 25),
        url="https://x/1",
        url_hash="h",
        title=title,
        body="b",
    )


def test_first_party_source_forces_tier2():
    r = LLMRouter(first_party_sources={"sec_edgar", "juchao", "caixin_telegram"})
    decision = r.decide(
        _art(source="sec_edgar"),
        verdict=Tier0Verdict(relevant=True, tier_hint="tier1", watchlist_hit=False, reason=""),
    )
    assert decision == "tier2"


def test_irrelevant_returns_skip():
    r = LLMRouter(first_party_sources=set())
    decision = r.decide(
        _art(),
        verdict=Tier0Verdict(
            relevant=False, tier_hint="tier1", watchlist_hit=False, reason="off topic"
        ),
    )
    assert decision == "skip"


def test_watchlist_hit_uses_tier2():
    r = LLMRouter(first_party_sources=set())
    decision = r.decide(
        _art(),
        verdict=Tier0Verdict(relevant=True, tier_hint="tier2", watchlist_hit=True, reason=""),
    )
    assert decision == "tier2"


def test_other_relevant_uses_tier1():
    r = LLMRouter(first_party_sources=set())
    decision = r.decide(
        _art(),
        verdict=Tier0Verdict(relevant=True, tier_hint="tier1", watchlist_hit=False, reason=""),
    )
    assert decision == "tier1"
