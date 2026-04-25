# tests/unit/llm/test_tier2_extractor.py
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.llm.clients.base import LLMResponse, TokenUsage
from news_pipeline.llm.extractors import Tier2DeepExtractor
from news_pipeline.llm.prompts.loader import PromptLoader


@pytest.fixture
def prompt(tmp_path: Path):
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


@pytest.mark.asyncio
async def test_tier2_with_entities(prompt):
    fake = AsyncMock()
    fake.call.return_value = LLMResponse(
        text="", json_payload={
            "summary": "出口管制",
            "related_tickers": ["NVDA", "TSM"],
            "sectors": ["semiconductor"],
            "event_type": "policy",
            "sentiment": "bearish",
            "magnitude": "high",
            "confidence": 0.9,
            "key_quotes": ["…"],
            "entities": [
                {"type": "company", "name": "NVIDIA", "ticker": "NVDA",
                 "market": "us", "aliases": ["英伟达"]},
                {"type": "company", "name": "TSMC", "ticker": "TSM",
                 "market": "us", "aliases": []},
            ],
            "relations": [
                {"subject_name": "NVIDIA", "predicate": "supplies",
                 "object_name": "TSMC", "confidence": 0.7}
            ],
        },
        usage=TokenUsage(2000, 500), model="claude-haiku-4-5",
    )
    art = RawArticle(
        source="reuters", market=Market.US,
        fetched_at=datetime(2026, 4, 25), published_at=datetime(2026, 4, 25),
        url="https://x/1", url_hash="h", title="t", body="b",
    )
    ext = Tier2DeepExtractor(client=fake, prompt=prompt)
    out = await ext.extract(art, raw_id=10, recent_context="")
    assert len(out.entities) == 2
    assert out.relations[0].predicate.value == "supplies"
