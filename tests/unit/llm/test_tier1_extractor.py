# tests/unit/llm/test_tier1_extractor.py
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.llm.clients.base import LLMResponse, TokenUsage
from news_pipeline.llm.extractors import Tier1Summarizer
from news_pipeline.llm.prompts.loader import PromptLoader


@pytest.fixture
def prompt(tmp_path: Path):
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


@pytest.mark.asyncio
async def test_tier1_returns_enriched(prompt):
    fake = AsyncMock()
    fake.call.return_value = LLMResponse(
        text="{}",
        json_payload={
            "summary": "..",
            "related_tickers": ["NVDA"],
            "sectors": ["semiconductor"],
            "event_type": "policy",
            "sentiment": "bearish",
            "magnitude": "high",
            "confidence": 0.8,
            "key_quotes": ["q"],
        },
        usage=TokenUsage(1500, 300),
        model="deepseek-v3",
    )
    art = RawArticle(
        source="x",
        market=Market.US,
        fetched_at=datetime(2026, 4, 25),
        published_at=datetime(2026, 4, 25),
        url="https://x/1",
        url_hash="h",
        title="t",
        body="b",
    )
    mock_cost = MagicMock()
    s = Tier1Summarizer(client=fake, prompt=prompt, cost=mock_cost)
    out = await s.summarize(art, raw_id=42)
    assert out.raw_id == 42
    assert out.related_tickers == ["NVDA"]
    assert out.entities == [] and out.relations == []
