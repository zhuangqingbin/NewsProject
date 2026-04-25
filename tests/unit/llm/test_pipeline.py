# tests/unit/llm/test_pipeline.py
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.exceptions import CostCeilingExceeded
from news_pipeline.llm.extractors import Tier0Verdict
from news_pipeline.llm.pipeline import LLMPipeline


def _art() -> RawArticle:
    return RawArticle(
        source="finnhub", market=Market.US,
        fetched_at=datetime(2026, 4, 25), published_at=datetime(2026, 4, 25),
        url="https://x/1", url_hash="h", title="NVDA up", body="b",
    )


@pytest.mark.asyncio
async def test_pipeline_routes_to_tier2_when_watchlist_hit():
    classifier = MagicMock()
    classifier.classify = AsyncMock(return_value=Tier0Verdict(
        relevant=True, tier_hint="tier2", watchlist_hit=True, reason="hit"))
    tier1 = MagicMock()
    tier1.summarize = AsyncMock()
    tier2 = MagicMock()
    tier2.extract = AsyncMock(return_value="enriched_2")
    router = MagicMock()
    router.decide = MagicMock(return_value="tier2")
    cost = MagicMock()
    cost.check = MagicMock()

    p = LLMPipeline(classifier, tier1, tier2, router, cost,
                    watchlist_us=["NVDA"], watchlist_cn=[])
    out = await p.process(_art(), raw_id=1)
    assert out == "enriched_2"
    tier2.extract.assert_awaited_once()
    tier1.summarize.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_skips_when_classifier_says_irrelevant():
    classifier = MagicMock()
    classifier.classify = AsyncMock(return_value=Tier0Verdict(
        relevant=False, tier_hint="tier1", watchlist_hit=False, reason=""))
    tier1, tier2 = MagicMock(), MagicMock()
    tier1.summarize, tier2.extract = AsyncMock(), AsyncMock()
    router = MagicMock()
    router.decide = MagicMock(return_value="skip")
    cost = MagicMock()
    cost.check = MagicMock()
    p = LLMPipeline(classifier, tier1, tier2, router, cost, [], [])
    out = await p.process(_art(), raw_id=1)
    assert out is None


@pytest.mark.asyncio
async def test_pipeline_cost_ceiling_short_circuits():
    classifier = MagicMock()
    classifier.classify = AsyncMock()
    cost = MagicMock()
    cost.check = MagicMock(side_effect=CostCeilingExceeded("over"))
    p = LLMPipeline(classifier, MagicMock(), MagicMock(), MagicMock(), cost, [], [])
    with pytest.raises(CostCeilingExceeded):
        await p.process(_art(), raw_id=1)
    classifier.classify.assert_not_awaited()
