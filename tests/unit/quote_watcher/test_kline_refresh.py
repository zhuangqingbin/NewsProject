import asyncio
from unittest.mock import AsyncMock

from quote_watcher.main import _kline_refresh_loop


async def test_background_refresh_stops_cleanly():
    stop = asyncio.Event()
    cache = AsyncMock()

    async def refresh(tickers, days):
        stop.set()
        return {}

    cache.load_for.side_effect = refresh
    await asyncio.wait_for(_kline_refresh_loop(stop, cache, ["600519"]), timeout=1)
    cache.load_for.assert_awaited_once_with(["600519"], days=250)
