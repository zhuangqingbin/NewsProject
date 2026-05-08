# tests/unit/pushers/test_dispatcher.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.common.enums import Market
from shared.common.contracts import CommonMessage
from shared.push.base import SendResult
from shared.push.dispatcher import PusherDispatcher


def _msg() -> CommonMessage:
    return CommonMessage(
        title="t",
        summary="s",
        source_label="x",
        source_url="https://x.com",
        badges=[],
        chart_url=None,
        deeplinks=[],
        market=Market.US,
    )


@pytest.mark.asyncio
async def test_dispatch_calls_each_in_parallel():
    p1 = MagicMock()
    p1.channel_id = "c1"
    p1.send = AsyncMock(return_value=SendResult(ok=True, http_status=200))
    p2 = MagicMock()
    p2.channel_id = "c2"
    p2.send = AsyncMock(return_value=SendResult(ok=False, http_status=500))
    d = PusherDispatcher({"c1": p1, "c2": p2})
    results = await d.dispatch(_msg(), channels=["c1", "c2"])
    assert results["c1"].ok and not results["c2"].ok
