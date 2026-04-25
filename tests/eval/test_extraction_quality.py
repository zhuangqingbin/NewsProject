import json
import os
from pathlib import Path

import pytest

GOLD_PATH = Path(__file__).parent / "gold_news.jsonl"


def _load_gold() -> list[dict]:  # type: ignore[type-arg]
    return [json.loads(line) for line in GOLD_PATH.read_text().splitlines() if line.strip()]


@pytest.mark.skipif(
    os.environ.get("RUN_EVAL") != "1",
    reason="opt-in: set RUN_EVAL=1",
)
@pytest.mark.asyncio
async def test_extraction_f1_above_baseline() -> None:
    """Run real LLM against gold set; require F1 >= 0.7 across event_type + sentiment."""
    from datetime import datetime

    from news_pipeline.common.contracts import RawArticle
    from news_pipeline.common.enums import Market

    # Build LLM extractor (uses real API keys from env)
    pytest.importorskip("anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("no ANTHROPIC_API_KEY")
    from news_pipeline.llm.clients.anthropic import AnthropicClient
    from news_pipeline.llm.extractors import Tier2DeepExtractor
    from news_pipeline.llm.prompts.loader import PromptLoader

    cl = AnthropicClient(api_key=api_key)
    prompt = PromptLoader(Path("config/prompts")).load("tier2_extract", "v1")
    ext = Tier2DeepExtractor(client=cl, prompt=prompt)

    gold = _load_gold()
    correct_event = correct_sent = 0
    for g in gold:
        art = RawArticle(
            source=g["source"],
            market=Market.US,
            fetched_at=datetime(2026, 4, 25),
            published_at=datetime(2026, 4, 25),
            url=f"https://eval/{g['id']}",
            url_hash=g["id"],
            title=g["title"],
            body=g["body"],
        )
        out = await ext.extract(art, raw_id=0)
        if out.event_type.value == g["expected"]["event_type"]:
            correct_event += 1
        if out.sentiment.value == g["expected"]["sentiment"]:
            correct_sent += 1

    n = len(gold)
    f1 = (correct_event + correct_sent) / (2 * n)
    assert f1 >= 0.7, f"F1={f1} below baseline 0.7"
