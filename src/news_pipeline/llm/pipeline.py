# src/news_pipeline/llm/pipeline.py
from typing import TYPE_CHECKING

from news_pipeline.common.contracts import EnrichedNews, RawArticle
from news_pipeline.llm.cost_tracker import CostTracker
from news_pipeline.llm.extractors import (
    Tier0Classifier,
    Tier1Summarizer,
    Tier2DeepExtractor,
)
from news_pipeline.llm.router import LLMRouter
from shared.observability.log import get_logger

if TYPE_CHECKING:
    from news_pipeline.rules.verdict import RulesVerdict

log = get_logger(__name__)


class LLMPipeline:
    def __init__(
        self,
        classifier: Tier0Classifier,
        tier1: Tier1Summarizer,
        tier2: Tier2DeepExtractor,
        router: LLMRouter,
        cost_tracker: CostTracker,
        watchlist_us: list[str],
        watchlist_cn: list[str],
        first_party_sources: set[str] | None = None,
    ) -> None:
        self._cls = classifier
        self._t1 = tier1
        self._t2 = tier2
        self._router = router
        self._cost = cost_tracker
        self._wl_us = watchlist_us
        self._wl_cn = watchlist_cn
        self._first_party_sources = first_party_sources or set()

    async def process(self, art: RawArticle, *, raw_id: int) -> EnrichedNews | None:
        await self._cost.check_async()

        verdict = await self._cls.classify(
            art,
            watchlist_us=self._wl_us,
            watchlist_cn=self._wl_cn,
        )
        decision = self._router.decide(art, verdict=verdict)

        if decision == "skip":
            log.debug("llm_skip", url_hash=art.url_hash, reason=verdict.reason)
            return None
        if decision == "tier1":
            return await self._t1.summarize(art, raw_id=raw_id)
        return await self._t2.extract(art, raw_id=raw_id, recent_context="")

    async def process_with_rules(
        self, art: RawArticle, verdict: "RulesVerdict", *, raw_id: int
    ) -> EnrichedNews | None:
        """Rules + LLM mode: rules already classified relevant, skip Tier-0.
        Direct ticker hit OR first-party source → Tier-2 deep extract.
        Otherwise → Tier-1 summary.
        """
        await self._cost.check_async()
        if verdict.tickers or art.source in self._first_party_sources:
            return await self._t2.extract(art, raw_id=raw_id, recent_context="")
        return await self._t1.summarize(art, raw_id=raw_id)
