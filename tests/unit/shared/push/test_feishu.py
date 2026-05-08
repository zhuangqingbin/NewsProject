# tests/unit/pushers/test_feishu.py
import json

import pytest
import respx
from httpx import Response

from news_pipeline.common.enums import Market
from shared.common.contracts import Badge, CommonMessage, Deeplink
from shared.push.feishu import FeishuPusher


def _msg() -> CommonMessage:
    return CommonMessage(
        title="NVDA -8%",
        summary="出口管制升级",
        source_label="Reuters",
        source_url="https://reut/x",
        badges=[Badge(text="bearish", color="red"), Badge(text="high", color="yellow")],
        chart_url="https://oss/chart.png",
        deeplinks=[Deeplink(label="原文", url="https://reut/x")],
        market=Market.US,
    )


@pytest.mark.asyncio
async def test_send_uses_card_format():
    async with respx.mock() as mock:
        route = mock.post("https://open.feishu.cn/hook/W").mock(
            return_value=Response(200, json={"code": 0, "msg": "ok"})
        )
        p = FeishuPusher(channel_id="feishu_us", webhook="https://open.feishu.cn/hook/W")
        result = await p.send(_msg())
        assert result.ok is True
        sent = json.loads(route.calls[0].request.read().decode())
        assert sent["msg_type"] == "interactive"
        assert "card" in sent
        # color tag conveys sentiment
        assert "red" in json.dumps(sent) or "danger" in json.dumps(sent)
