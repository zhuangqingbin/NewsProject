# tests/unit/classifier/test_llm_judge.py
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from news_pipeline.classifier.llm_judge import LLMJudge
from news_pipeline.common.contracts import EnrichedNews
from news_pipeline.common.enums import EventType, Magnitude, Sentiment
from news_pipeline.llm.clients.base import LLMResponse, TokenUsage


def _enriched() -> EnrichedNews:
    return EnrichedNews(
        raw_id=1, summary="s", related_tickers=["NVDA"], sectors=[],
        event_type=EventType.OTHER, sentiment=Sentiment.NEUTRAL,
        magnitude=Magnitude.MEDIUM, confidence=0.7, key_quotes=[],
        entities=[], relations=[], model_used="x",
        extracted_at=datetime(2026, 4, 25),
    )


@pytest.mark.asyncio
async def test_judge_critical():
    fake = AsyncMock()
    fake.call.return_value = LLMResponse(
        text="", json_payload={"is_critical": True, "reason": "持仓股利空"},
        usage=TokenUsage(200, 30), model="deepseek-v3",
    )
    j = LLMJudge(client=fake, model="deepseek-v3")
    is_crit, reason = await j.judge(_enriched(), watchlist_tickers=["NVDA"])
    assert is_crit is True
    assert "持仓" in reason
