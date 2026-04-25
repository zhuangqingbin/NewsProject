# tests/unit/classifier/test_importance.py
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.classifier.importance import ImportanceClassifier
from news_pipeline.classifier.rules import RuleHit
from news_pipeline.common.contracts import EnrichedNews
from news_pipeline.common.enums import EventType, Magnitude, Sentiment


def _e(m="medium") -> EnrichedNews:
    return EnrichedNews(
        raw_id=1,
        summary="s",
        related_tickers=["NVDA"],
        sectors=[],
        event_type=EventType.OTHER,
        sentiment=Sentiment.NEUTRAL,
        magnitude=Magnitude(m),
        confidence=0.7,
        key_quotes=[],
        entities=[],
        relations=[],
        model_used="x",
        extracted_at=datetime(2026, 4, 25),
    )


@pytest.mark.asyncio
async def test_high_score_critical_no_judge():
    rules = MagicMock()
    rules.evaluate.return_value = [RuleHit("first_party_source", 30), RuleHit("sentiment_high", 40)]
    rules.score = lambda hits: 70
    judge = MagicMock()
    judge.judge = AsyncMock()
    cls = ImportanceClassifier(
        rules=rules, judge=judge, gray_zone=(40, 70), watchlist_tickers=["NVDA"]
    )
    scored = await cls.score_news(_e(), source="sec_edgar")
    assert scored.is_critical is True
    judge.judge.assert_not_awaited()


@pytest.mark.asyncio
async def test_low_score_not_critical_no_judge():
    rules = MagicMock()
    rules.evaluate.return_value = []
    rules.score = lambda hits: 10
    judge = MagicMock()
    judge.judge = AsyncMock()
    cls = ImportanceClassifier(
        rules=rules, judge=judge, gray_zone=(40, 70), watchlist_tickers=["NVDA"]
    )
    scored = await cls.score_news(_e(), source="finnhub")
    assert scored.is_critical is False
    judge.judge.assert_not_awaited()


@pytest.mark.asyncio
async def test_gray_zone_calls_judge():
    rules = MagicMock()
    rules.evaluate.return_value = [RuleHit("filing", 50)]
    rules.score = lambda hits: 50
    judge = MagicMock()
    judge.judge = AsyncMock(return_value=(True, "持仓"))
    cls = ImportanceClassifier(
        rules=rules, judge=judge, gray_zone=(40, 70), watchlist_tickers=["NVDA"]
    )
    scored = await cls.score_news(_e(), source="finnhub")
    judge.judge.assert_awaited_once()
    assert scored.is_critical is True
    assert scored.llm_reason == "持仓"
