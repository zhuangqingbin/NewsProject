# tests/unit/pushers/test_wecom.py
import json

import pytest
import respx
from httpx import Response

from news_pipeline.common.contracts import Badge, CommonMessage, Deeplink
from news_pipeline.common.enums import Market
from shared.push.wecom import WecomPusher


def _msg() -> CommonMessage:
    return CommonMessage(
        title="NVDA -8%",
        summary="出口管制",
        source_label="Reuters",
        source_url="https://reut/x",
        badges=[Badge(text="bearish", color="red")],
        chart_url=None,
        deeplinks=[Deeplink(label="原文", url="https://reut/x")],
        market=Market.US,
    )


@pytest.mark.asyncio
async def test_send_uses_markdown_msgtype():
    async with respx.mock() as mock:
        route = mock.post("https://qyapi.weixin.qq.com/W").mock(
            return_value=Response(200, json={"errcode": 0})
        )
        p = WecomPusher(channel_id="wecom_us", webhook="https://qyapi.weixin.qq.com/W")
        result = await p.send(_msg())
        assert result.ok is True
        sent = json.loads(route.calls[0].request.read().decode())
        assert sent["msgtype"] == "markdown"
        assert "**NVDA" in sent["markdown"]["content"]
