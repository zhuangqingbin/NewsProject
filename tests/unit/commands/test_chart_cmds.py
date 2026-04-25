from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.commands.dispatcher import CommandDispatcher
from news_pipeline.commands.handlers.charts import register_chart_cmds

_PNG = b"\x89PNG\r\n\x1a\n" + b"X" * 100


@pytest.mark.asyncio
async def test_chart_returns_ok_message():
    factory = MagicMock()
    factory.render_kline = AsyncMock(return_value=_PNG)
    d = CommandDispatcher()
    register_chart_cmds(d, chart_factory=factory)
    out = await d.handle_text("/chart NVDA 30d", ctx={})
    assert "NVDA" in out
    assert "bytes" in out
    factory.render_kline.assert_awaited_once()
