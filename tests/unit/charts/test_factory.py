# tests/unit/charts/test_factory.py
import pytest

from news_pipeline.charts.factory import ChartFactory, ChartRequest


_PNG_MAGIC = b"\x89PNG"


@pytest.mark.asyncio
async def test_render_kline_returns_png_bytes():
    renderer = lambda df, ticker, news_markers: _PNG_MAGIC + b"\r\n\x1a\n" + b"X" * 100
    f = ChartFactory(
        kline_renderer=renderer,
        data_loader=lambda t, w: __import__("pandas").DataFrame(),
    )
    result = await f.render_kline(ChartRequest(ticker="NVDA", kind="kline", window="30d"))
    assert isinstance(result, bytes)
    assert result[:4] == _PNG_MAGIC


@pytest.mark.asyncio
async def test_render_kline_no_data_loader_raises():
    renderer = lambda df, ticker, news_markers: _PNG_MAGIC
    f = ChartFactory(kline_renderer=renderer)
    with pytest.raises(RuntimeError, match="no data_loader"):
        await f.render_kline(ChartRequest(ticker="NVDA", kind="kline", window="30d"))


@pytest.mark.asyncio
async def test_render_kline_bad_renderer_raises():
    renderer = lambda df, ticker, news_markers: "not bytes"
    f = ChartFactory(
        kline_renderer=renderer,
        data_loader=lambda t, w: __import__("pandas").DataFrame(),
    )
    with pytest.raises(RuntimeError, match="renderer must return bytes"):
        await f.render_kline(ChartRequest(ticker="NVDA", kind="kline", window="30d"))
