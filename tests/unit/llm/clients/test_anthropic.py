# tests/unit/llm/clients/test_anthropic.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.llm.clients.anthropic import AnthropicClient
from news_pipeline.llm.clients.base import LLMRequest


@pytest.mark.asyncio
async def test_tool_use_call_returns_input():
    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(type="tool_use", input={"summary": "ok"})]
    fake_msg.usage = MagicMock(input_tokens=100, output_tokens=20,
                               cache_read_input_tokens=80,
                               cache_creation_input_tokens=0)
    sdk_client = MagicMock()
    sdk_client.messages.create = AsyncMock(return_value=fake_msg)

    c = AnthropicClient(api_key="k", _client=sdk_client)
    req = LLMRequest(
        model="claude-haiku-4-5", system="sys", user="usr",
        output_schema={"type": "object",
                       "properties": {"summary": {"type": "string"}},
                       "required": ["summary"]},
        cache_segments=["system"],
    )
    out = await c.call(req)
    assert out.json_payload == {"summary": "ok"}
    assert out.usage.input_tokens == 100
