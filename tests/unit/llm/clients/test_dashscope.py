# tests/unit/llm/clients/test_dashscope.py
import pytest
import respx
from httpx import Response

from news_pipeline.llm.clients.base import LLMRequest
from news_pipeline.llm.clients.dashscope import DashScopeClient


@pytest.mark.asyncio
async def test_call_returns_parsed_json():
    response_payload = {
        "choices": [
            {
                "message": {"content": '{"x": 1, "y": "abc"}'},
                "finish_reason": "stop",
            }
        ],
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }
    async with respx.mock() as mock:
        mock.post(url__regex=r"https://dashscope\.aliyuncs\.com/.*").mock(
            return_value=Response(200, json=response_payload)
        )
        c = DashScopeClient(api_key="k", base_url="https://dashscope.aliyuncs.com/v1")
        req = LLMRequest(
            model="deepseek-v3", system="sys", user="usr", json_mode=True, max_tokens=200
        )
        out = await c.call(req)
        assert out.json_payload == {"x": 1, "y": "abc"}
        assert out.usage.input_tokens == 100
        assert out.usage.output_tokens == 20
