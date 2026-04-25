# src/news_pipeline/llm/router.py
from typing import Literal

from news_pipeline.common.contracts import RawArticle
from news_pipeline.llm.extractors import Tier0Verdict

Tier = Literal["skip", "tier1", "tier2"]


class LLMRouter:
    def __init__(self, *, first_party_sources: set[str]) -> None:
        self._first_party = first_party_sources

    def decide(self, art: RawArticle, *, verdict: Tier0Verdict) -> Tier:
        # First-party sources always go to Tier-2 regardless of verdict
        if art.source in self._first_party:
            return "tier2"
        # Irrelevant articles are skipped
        if not verdict.relevant:
            return "skip"
        # Watchlist hits or tier2 hint → deep extraction
        if verdict.watchlist_hit or verdict.tier_hint == "tier2":
            return "tier2"
        # Default: summarize only
        return "tier1"
