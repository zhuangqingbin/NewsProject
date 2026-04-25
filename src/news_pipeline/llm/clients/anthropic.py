# src/news_pipeline/llm/clients/anthropic.py
from typing import Any

import anthropic

from news_pipeline.llm.clients.base import (
    LLMRequest,
    LLMResponse,
    TokenUsage,
    parse_json_or_none,
)


class AnthropicClient:
    def __init__(
        self,
        *,
        api_key: str,
        _client: Any | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._client = _client or anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)

    async def call(self, req: LLMRequest) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
        }
        if "system" in req.cache_segments:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": req.system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            kwargs["system"] = req.system

        kwargs["messages"] = [{"role": "user", "content": req.user}]

        if req.output_schema is not None:
            kwargs["tools"] = [
                {
                    "name": "emit",
                    "description": "Return structured result",
                    "input_schema": req.output_schema,
                }
            ]
            kwargs["tool_choice"] = {"type": "tool", "name": "emit"}

        msg = await self._client.messages.create(**kwargs)

        json_payload: dict[str, Any] | None = None
        text = ""
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use":
                json_payload = dict(block.input)
                break
            if getattr(block, "type", None) == "text":
                text += block.text

        if json_payload is None and text:
            json_payload = parse_json_or_none(text)

        u = msg.usage
        return LLMResponse(
            text=text,
            json_payload=json_payload,
            usage=TokenUsage(
                input_tokens=int(getattr(u, "input_tokens", 0)),
                output_tokens=int(getattr(u, "output_tokens", 0)),
            ),
            model=req.model,
        )
