from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from news_pipeline.commands.dispatcher import CommandDispatcher
from news_pipeline.commands.handlers.news import register_news_cmds
from news_pipeline.commands.handlers.watchlist import register_watchlist_cmds


@pytest.mark.asyncio
async def test_watch_adds_to_yaml(tmp_path: Path):
    wl = tmp_path / "watchlist.yml"
    wl.write_text(yaml.safe_dump({"us": [], "cn": [], "macro": [], "sectors": []}))
    d = CommandDispatcher()
    register_watchlist_cmds(d, watchlist_path=wl)
    out = await d.handle_text("/watch NVDA", ctx={})
    assert "已加入" in out
    data = yaml.safe_load(wl.read_text())
    assert any(e["ticker"] == "NVDA" for e in data["us"])


@pytest.mark.asyncio
async def test_list_shows_all(tmp_path: Path):
    wl = tmp_path / "watchlist.yml"
    wl.write_text(
        yaml.safe_dump(
            {
                "us": [{"ticker": "NVDA"}],
                "cn": [{"ticker": "600519"}],
                "macro": ["FOMC"],
                "sectors": ["semiconductor"],
            }
        )
    )
    d = CommandDispatcher()
    register_watchlist_cmds(d, watchlist_path=wl)
    out = await d.handle_text("/list", ctx={})
    assert "NVDA" in out and "600519" in out


@pytest.mark.asyncio
async def test_news_shows_recent():
    proc_dao = MagicMock()
    proc_dao.list_recent_for_ticker = AsyncMock(
        return_value=[
            MagicMock(summary="出口管制升级", extracted_at="2026-04-25"),
        ]
    )
    d = CommandDispatcher()
    register_news_cmds(d, processed_dao=proc_dao)
    out = await d.handle_text("/news NVDA", ctx={})
    assert "出口管制" in out
