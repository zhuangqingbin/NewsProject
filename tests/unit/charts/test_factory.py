# tests/unit/charts/test_factory.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.charts.factory import ChartFactory, ChartRequest


@pytest.mark.asyncio
async def test_cache_hit_skips_render():
    cache = MagicMock()
    cache.get = AsyncMock(return_value=MagicMock(oss_url="https://oss/x.png"))
    cache.put = AsyncMock()
    renderer = MagicMock(return_value=b"PNG")
    uploader = MagicMock()
    uploader.upload = MagicMock()
    f = ChartFactory(cache_dao=cache, kline_renderer=renderer, uploader=uploader)
    url = await f.render_kline(ChartRequest(ticker="NVDA", kind="kline", window="30d", params={}))
    assert url == "https://oss/x.png"
    renderer.assert_not_called()
    uploader.upload.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_renders_uploads_caches():
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.put = AsyncMock()
    renderer = MagicMock(return_value=b"PNG")
    uploader = MagicMock()
    uploader.upload = MagicMock(return_value="https://oss/new.png")
    f = ChartFactory(
        cache_dao=cache,
        kline_renderer=renderer,
        uploader=uploader,
        data_loader=lambda t, w: __import__("pandas").DataFrame(),
    )
    url = await f.render_kline(ChartRequest(ticker="NVDA", kind="kline", window="30d", params={}))
    assert url == "https://oss/new.png"
    cache.put.assert_awaited_once()
