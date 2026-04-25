# tests/unit/llm/test_tier0_extractor.py
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.llm.clients.base import LLMResponse, TokenUsage
from news_pipeline.llm.extractors import Tier0Classifier
from news_pipeline.llm.prompts.loader import PromptLoader


@pytest.fixture
def prompt_handle(tmp_path: Path):
    p = tmp_path / "tier0_classify.v1.yaml"
    p.write_text("""
name: tier0_classify
version: 1
model_target: deepseek-v3
system: "you are classifier"
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


@pytest.mark.asyncio
async def test_classify_returns_parsed(prompt_handle):
    fake = AsyncMock()
    fake.call.return_value = LLMResponse(
        text='{"relevant":true,"tier_hint":"tier2","watchlist_hit":true,"reason":"NVDA hit"}',
        json_payload={"relevant": True, "tier_hint": "tier2",
                      "watchlist_hit": True, "reason": "NVDA hit"},
        usage=TokenUsage(100, 30), model="deepseek-v3",
    )
    cls = Tier0Classifier(client=fake, prompt=prompt_handle)
    art = RawArticle(
        source="finnhub", market=Market.US,
        fetched_at="2026-04-25T00:00:00", published_at="2026-04-25T00:00:00",
        url="https://x/1", url_hash="h", title="NVDA up 5%",
    )
    out = await cls.classify(art, watchlist_us=["NVDA"], watchlist_cn=[])
    assert out.relevant is True and out.watchlist_hit is True
