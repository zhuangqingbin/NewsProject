# tests/unit/pushers/test_telegram.py
import pytest
import respx
from httpx import Response

from news_pipeline.common.contracts import (
    Badge,
    CommonMessage,
    Deeplink,
)
from news_pipeline.common.enums import Market
from news_pipeline.pushers.telegram import TelegramPusher


def _msg() -> CommonMessage:
    return CommonMessage(
        title="NVDA *up* 5%",
        summary="出口管制 [详情]",
        source_label="Reuters",
        source_url="https://reut/x",
        badges=[Badge(text="NVDA", color="blue"), Badge(text="bearish", color="red")],
        chart_url=None,
        deeplinks=[
            Deeplink(label="原文", url="https://reut/x"),
            Deeplink(label="Yahoo", url="https://yhoo/x"),
        ],
        market=Market.US,
    )


@pytest.mark.asyncio
async def test_send_escapes_and_returns_ok():
    async with respx.mock() as mock:
        route = mock.post("https://api.telegram.org/botT/sendMessage").mock(
            return_value=Response(200, json={"ok": True})
        )
        p = TelegramPusher(channel_id="tg_us", bot_token="T", chat_id="C")
        result = await p.send(_msg())
        assert result.ok is True
        body = route.calls[0].request.read().decode()
        # MarkdownV2 escaping required
        assert "\\*" in body or "%5C%2A" in body  # the * was escaped
        assert "MarkdownV2" in body


@pytest.mark.asyncio
async def test_send_failure_returns_not_ok():
    async with respx.mock() as mock:
        mock.post("https://api.telegram.org/botT/sendMessage").mock(
            return_value=Response(400, json={"ok": False, "description": "bad"})
        )
        p = TelegramPusher(channel_id="tg_us", bot_token="T", chat_id="C", max_retries=1)
        result = await p.send(_msg())
        assert result.ok is False
        assert result.http_status == 400
