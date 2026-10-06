from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from news_pipeline.assess.client import ChatClient, ChatRequestError


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadError])
@respx.mock
async def test_client_retries_network_errors_twice_then_recovers(monkeypatch, error_type):
    sleep = AsyncMock()
    monkeypatch.setattr("news_pipeline.assess.client.asyncio.sleep", sleep)
    route = respx.post("https://example.com/v1/chat/completions").mock(
        side_effect=[
            error_type("network unavailable"),
            error_type("network unavailable"),
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "{}"}}],
                    "usage": {"prompt_tokens": 123, "completion_tokens": 45},
                },
            ),
        ]
    )
    client = ChatClient(api_key="test", base_url="https://example.com/v1")
    try:
        result = await client.chat_json(model="model", system="system", user="user", max_tokens=40)
    finally:
        await client.close()

    assert route.call_count == 3
    assert [call.args for call in sleep.await_args_list] == [(2,), (6,)]
    assert [attempt.error for attempt in result.attempts] == [
        error_type.__name__,
        error_type.__name__,
        None,
    ]
    assert [(attempt.tokens_in, attempt.tokens_out) for attempt in result.attempts] == [
        (0, 0),
        (0, 0),
        (123, 45),
    ]


@respx.mock
async def test_client_stops_after_three_network_failures(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("news_pipeline.assess.client.asyncio.sleep", sleep)
    route = respx.post("https://example.com/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("network unavailable")
    )
    client = ChatClient(api_key="test", base_url="https://example.com/v1")
    try:
        with pytest.raises(ChatRequestError) as failure:
            await client.chat_json(model="model", system="system", user="user", max_tokens=40)
    finally:
        await client.close()

    assert route.call_count == 3
    assert [call.args for call in sleep.await_args_list] == [(2,), (6,)]
    assert len(failure.value.attempts) == 3
    assert all(attempt.error == "ConnectError" for attempt in failure.value.attempts)
