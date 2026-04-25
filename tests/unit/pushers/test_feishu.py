# tests/unit/pushers/test_feishu.py
import json

import pytest
import respx
from httpx import Response

from news_pipeline.common.contracts import (
    Badge,
    CommonMessage,
    Deeplink,
)
from news_pipeline.common.enums import Market
from news_pipeline.pushers.common.feishu_auth import FeishuTenantAuth
from news_pipeline.pushers.feishu import FeishuPusher


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


def _msg_with_chart_image() -> CommonMessage:
    return CommonMessage(
        title="NVDA chart",
        summary="K线图",
        source_label="Reuters",
        source_url="https://reut/x",
        badges=[Badge(text="bearish", color="red")],
        chart_url=None,
        chart_image=b"\x89PNG\r\n\x1a\nFAKEDATA",
        deeplinks=[],
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


@pytest.mark.asyncio
async def test_send_with_chart_image_uploads_then_includes_img_key():
    async with respx.mock() as mock:
        # Mock tenant_access_token endpoint
        mock.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        ).mock(
            return_value=Response(
                200,
                json={"code": 0, "tenant_access_token": "tok123", "expire": 7200},
            )
        )
        # Mock image upload endpoint
        mock.post("https://open.feishu.cn/open-apis/im/v1/images").mock(
            return_value=Response(
                200,
                json={"code": 0, "data": {"image_key": "img_key_abc"}},
            )
        )
        # Mock webhook
        webhook_route = mock.post("https://open.feishu.cn/hook/W").mock(
            return_value=Response(200, json={"code": 0, "msg": "ok"})
        )

        auth = FeishuTenantAuth(app_id="app1", app_secret="sec1")
        p = FeishuPusher(
            channel_id="feishu_us",
            webhook="https://open.feishu.cn/hook/W",
            image_auth=auth,
        )
        result = await p.send(_msg_with_chart_image())
        assert result.ok is True

        # Webhook was called
        assert webhook_route.called
        sent = json.loads(webhook_route.calls[0].request.read().decode())
        card_json = json.dumps(sent)
        # img_key from upload should be in card
        assert "img_key_abc" in card_json
        # img element present with correct tag
        elements = sent["card"]["elements"]
        img_elements = [e for e in elements if e.get("tag") == "img"]
        assert len(img_elements) == 1
        assert img_elements[0]["img_key"] == "img_key_abc"
