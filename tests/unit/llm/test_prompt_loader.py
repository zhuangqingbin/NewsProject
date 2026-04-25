# tests/unit/llm/test_prompt_loader.py
from pathlib import Path

import pytest

from news_pipeline.llm.prompts.loader import PromptLoader


def test_load_versioned_prompt(tmp_path: Path):
    p = tmp_path / "tier2_extract.v1.yaml"
    p.write_text("""
name: tier2_extract
version: 1
model_target: claude-haiku-4-5-20251001
description: test
cache_segments: [system]
system: "you are an analyst"
output_schema_inline:
  type: object
  properties:
    summary: {type: string}
  required: [summary]
user_template: "title={title}"
guardrails:
  max_input_tokens: 4000
  retry_on_invalid_json: 1
  fallback_model: deepseek-v3
""")
    loader = PromptLoader(tmp_path)
    pr = loader.load("tier2_extract", "v1")
    assert pr.name == "tier2_extract"
    assert pr.version == 1
    rendered = pr.render(title="hello")
    assert "title=hello" in rendered.user
    assert pr.guardrails.fallback_model == "deepseek-v3"


def test_unknown_version_raises(tmp_path: Path):
    loader = PromptLoader(tmp_path)
    with pytest.raises(FileNotFoundError):
        loader.load("nope", "v9")
