# src/news_pipeline/llm/clients/base.py
import json
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


def parse_json_or_none(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
