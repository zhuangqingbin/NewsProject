# src/news_pipeline/llm/clients/base.py
import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMRequest:
    model: str
    system: str
    user: str
    json_mode: bool = False
    output_schema: dict[str, Any] | None = None
    max_tokens: int = 1000
    cache_segments: list[str] = field(default_factory=list)
    few_shot_examples: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class LLMResponse:
    text: str
    json_payload: dict[str, Any] | None
    usage: TokenUsage
    model: str


class LLMClient(Protocol):
    async def call(self, req: LLMRequest) -> LLMResponse: ...


# Matches ```json ... ``` or ``` ... ``` fenced code blocks
_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL | re.IGNORECASE)


def parse_json_or_none(text: str) -> dict[str, Any] | None:
    """Best-effort JSON extraction from LLM output.

    Handles three common cases:
    1. Pure JSON: ``{"x": 1}``
    2. Markdown-fenced: ```` ```json\n{"x":1}\n``` ````
    3. JSON embedded in prose: ``Here is the result: {"x":1}``

    Returns None if no parseable object found.
    """
    if not text:
        return None
    candidates: list[str] = [text.strip()]

    # Strip markdown fence
    fenced = _FENCE_RE.findall(text)
    candidates.extend(fenced)

    # Try to find first '{' to last '}' for prose-wrapped JSON
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return dict(parsed)
        except (json.JSONDecodeError, ValueError):
            continue
    return None
