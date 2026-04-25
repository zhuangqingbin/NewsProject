from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.commands.dispatcher import CommandDispatcher
from news_pipeline.commands.handlers.charts import register_chart_cmds


@pytest.mark.asyncio
async def test_chart_returns_url():
    factory = MagicMock()
    factory.render_kline = AsyncMock(return_value="https://oss/x.png")
    d = CommandDispatcher()
    register_chart_cmds(d, chart_factory=factory)
    out = await d.handle_text("/chart NVDA 30d", ctx={})
    assert "oss/x.png" in out
    factory.render_kline.assert_awaited_once()
