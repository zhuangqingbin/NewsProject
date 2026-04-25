from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.commands.dispatcher import CommandDispatcher
from news_pipeline.commands.handlers.ops import register_ops_cmds


@pytest.mark.asyncio
async def test_cost_today():
    cost = MagicMock()
    cost.today_cost_cny = MagicMock(return_value=1.42)
    cost.remaining_today = MagicMock(return_value=3.58)
    d = CommandDispatcher()
    register_ops_cmds(d, cost=cost, state_dao=MagicMock(), digest_runner=AsyncMock())
    out = await d.handle_text("/cost", ctx={})
    assert "1.42" in out


@pytest.mark.asyncio
async def test_pause():
    state = MagicMock()
    state.set_paused = AsyncMock()
    d = CommandDispatcher()
    register_ops_cmds(d, cost=MagicMock(), state_dao=state, digest_runner=AsyncMock())
    out = await d.handle_text("/pause xueqiu", ctx={})
    assert "暂停" in out
    state.set_paused.assert_awaited_once()
