# tests/unit/llm/test_tier2_dashscope_fallback.py
"""Integration-style test: Tier2DeepExtractor with DashScope client + model_override."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.llm.clients.base import LLMRequest, LLMResponse, TokenUsage
from news_pipeline.llm.extractors import Tier2DeepExtractor
from news_pipeline.llm.prompts.loader import PromptLoader


@pytest.fixture
def tier2_prompt(tmp_path: Path):
    (tmp_path / "tier2_extract.v1.yaml").write_text("""
name: tier2_extract
version: 1
model_target: claude-haiku-4-5-20251001
cache_segments: [system]
system: deep extractor
output_schema_inline: {type: object, required: [summary], properties: {summary: {type: string}}}
user_template: "src={source} t={title} body={body} ctx={recent_context}"
guardrails: {max_input_tokens: 4000, retry_on_invalid_json: 1, fallback_model: deepseek-v3}
""")
    return PromptLoader(tmp_path).load("tier2_extract", "v1")


@pytest.fixture
def raw_article():
    return RawArticle(
        source="reuters",
        market=Market.US,
        fetched_at=datetime(2026, 4, 25),
        published_at=datetime(2026, 4, 25),
        url="https://example.com/1",
        url_hash="abc123",
        title="Fed raises rates",
        body="The Fed announced a 25bp rate hike.",
    )


@pytest.mark.asyncio
async def test_tier2_extractor_works_with_dashscope_client(tier2_prompt, raw_article):
    """Tier2 with model_override='deepseek-v3' sends correct model + json_mode=True to client."""
    mock_dashscope = AsyncMock()
    mock_dashscope.call.return_value = LLMResponse(
        text="",
        json_payload={
            "summary": "Fed hike",
            "related_tickers": [],
            "sectors": ["financials"],
            "event_type": "policy",
            "sentiment": "bearish",
            "magnitude": "medium",
            "confidence": 0.85,
            "key_quotes": [],
            "entities": [],
            "relations": [],
        },
        usage=TokenUsage(1000, 200),
        model="deepseek-v3",
    )

    mock_cost = MagicMock()
    ext = Tier2DeepExtractor(
        client=mock_dashscope,
        prompt=tier2_prompt,
        cost=mock_cost,
        model_override="deepseek-v3",
    )

    result = await ext.extract(raw_article, raw_id=42, recent_context="")

    # Verify the LLMRequest passed to the client has the overridden model and json_mode=True
    assert mock_dashscope.call.call_count == 1
    req: LLMRequest = mock_dashscope.call.call_args[0][0]
    assert req.model == "deepseek-v3"
    assert req.json_mode is True

    # Verify output is correctly parsed
    assert result.raw_id == 42
    assert result.summary == "Fed hike"


@pytest.mark.asyncio
async def test_tier2_extractor_without_override_uses_prompt_model(tier2_prompt, raw_article):
    """Tier2 without model_override uses the prompt's model_target (backwards compat)."""
    mock_client = AsyncMock()
    mock_client.call.return_value = LLMResponse(
        text="",
        json_payload={
            "summary": "test",
            "related_tickers": [],
            "sectors": [],
            "event_type": "other",
            "sentiment": "neutral",
            "magnitude": "low",
            "confidence": 0.7,
            "key_quotes": [],
            "entities": [],
            "relations": [],
        },
        usage=TokenUsage(500, 100),
        model="claude-haiku-4-5-20251001",
    )

    mock_cost = MagicMock()
    ext = Tier2DeepExtractor(client=mock_client, prompt=tier2_prompt, cost=mock_cost)

    await ext.extract(raw_article, raw_id=1)

    req: LLMRequest = mock_client.call.call_args[0][0]
    # No override → uses prompt's model_target
    assert req.model == "claude-haiku-4-5-20251001"
    # json_mode is always True now
    assert req.json_mode is True
