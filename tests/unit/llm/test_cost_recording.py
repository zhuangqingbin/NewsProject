# tests/unit/llm/test_cost_recording.py
"""Regression: cost.record() is called exactly once per LLM extractor call (C1)."""
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.llm.clients.base import LLMResponse, TokenUsage
from news_pipeline.llm.extractors import Tier0Classifier, Tier1Summarizer, Tier2DeepExtractor
from news_pipeline.llm.prompts.loader import PromptLoader

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _raw_article() -> RawArticle:
    return RawArticle(
        source="finnhub",
        market=Market.US,
        fetched_at=datetime(2026, 4, 25),
        published_at=datetime(2026, 4, 25),
        url="https://x/1",
        url_hash="h",
        title="NVDA export controls",
        body="body text",
    )


def _tier0_prompt(tmp_path: Path):
    p = tmp_path / "tier0_classify.v1.yaml"
    p.write_text("""
name: tier0_classify
version: 1
model_target: deepseek-v3
system: "classifier"
output_schema_inline:
  type: object
  required: [relevant, tier_hint, watchlist_hit, reason]
  properties:
    relevant: {type: boolean}
    tier_hint: {type: string}
    watchlist_hit: {type: boolean}
    reason: {type: string}
user_template: "title={title} source={source} tickers={tickers} watchlist={watchlist}"
guardrails:
  max_input_tokens: 1000
  retry_on_invalid_json: 1
""")
    return PromptLoader(tmp_path).load("tier0_classify", "v1")


def _tier1_prompt(tmp_path: Path):
    p = tmp_path / "tier1_summarize.v1.yaml"
    p.write_text("""
name: tier1_summarize
version: 1
model_target: deepseek-v3
system: sum
output_schema_inline:
  type: object
  required: [summary, related_tickers, sectors, event_type, sentiment, magnitude, confidence]
  properties:
    summary: {type: string}
    related_tickers: {type: array}
    sectors: {type: array}
    event_type: {type: string}
    sentiment: {type: string}
    magnitude: {type: string}
    confidence: {type: number}
    key_quotes: {type: array}
user_template: "src={source} t={title} body={body}"
guardrails:
  max_input_tokens: 4000
  retry_on_invalid_json: 1
""")
    return PromptLoader(tmp_path).load("tier1_summarize", "v1")


def _tier2_prompt(tmp_path: Path):
    (tmp_path / "tier2_extract.v1.yaml").write_text("""
name: tier2_extract
version: 1
model_target: claude-haiku-4-5-20251001
cache_segments: [system]
system: deep
output_schema_inline: {type: object, required: [summary], properties: {summary: {type: string}}}
user_template: "src={source} t={title} body={body} ctx={recent_context}"
guardrails: {max_input_tokens: 4000, retry_on_invalid_json: 1, fallback_model: deepseek-v3}
""")
    return PromptLoader(tmp_path).load("tier2_extract", "v1")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier0_records_cost_once(tmp_path: Path) -> None:
    usage = TokenUsage(input_tokens=100, output_tokens=30)
    fake_client = AsyncMock()
    fake_client.call.return_value = LLMResponse(
        text="",
        json_payload={
            "relevant": True,
            "tier_hint": "tier1",
            "watchlist_hit": False,
            "reason": "ok",
        },
        usage=usage,
        model="deepseek-v3",
    )
    mock_cost = MagicMock()
    cls = Tier0Classifier(client=fake_client, prompt=_tier0_prompt(tmp_path), cost=mock_cost)

    await cls.classify(_raw_article(), watchlist_us=["NVDA"], watchlist_cn=[])

    mock_cost.record.assert_called_once_with(model="deepseek-v3", usage=usage)


@pytest.mark.asyncio
async def test_tier1_records_cost_once(tmp_path: Path) -> None:
    usage = TokenUsage(input_tokens=1500, output_tokens=300)
    fake_client = AsyncMock()
    fake_client.call.return_value = LLMResponse(
        text="",
        json_payload={
            "summary": "s",
            "related_tickers": [],
            "sectors": [],
            "event_type": "other",
            "sentiment": "neutral",
            "magnitude": "low",
            "confidence": 0.5,
            "key_quotes": [],
        },
        usage=usage,
        model="deepseek-v3",
    )
    mock_cost = MagicMock()
    s = Tier1Summarizer(client=fake_client, prompt=_tier1_prompt(tmp_path), cost=mock_cost)

    await s.summarize(_raw_article(), raw_id=1)

    mock_cost.record.assert_called_once_with(model="deepseek-v3", usage=usage)


@pytest.mark.asyncio
async def test_tier2_records_cost_once(tmp_path: Path) -> None:
    usage = TokenUsage(input_tokens=2000, output_tokens=500)
    fake_client = AsyncMock()
    fake_client.call.return_value = LLMResponse(
        text="",
        json_payload={
            "summary": "s",
            "related_tickers": [],
            "sectors": [],
            "event_type": "other",
            "sentiment": "neutral",
            "magnitude": "low",
            "confidence": 0.5,
            "key_quotes": [],
            "entities": [],
            "relations": [],
        },
        usage=usage,
        model="claude-haiku-4-5-20251001",
    )
    mock_cost = MagicMock()
    ext = Tier2DeepExtractor(client=fake_client, prompt=_tier2_prompt(tmp_path), cost=mock_cost)

    await ext.extract(_raw_article(), raw_id=1, recent_context="")

    mock_cost.record.assert_called_once_with(model="claude-haiku-4-5-20251001", usage=usage)
