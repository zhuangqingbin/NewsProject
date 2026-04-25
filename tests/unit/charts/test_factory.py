# tests/unit/charts/test_factory.py
import pytest

from news_pipeline.charts.factory import ChartFactory, ChartRequest

_PNG_MAGIC = b"\x89PNG"


def _make_renderer(return_val: bytes):  # type: ignore[no-untyped-def]
    def renderer(df, ticker, news_markers):  # type: ignore[no-untyped-def]
        return return_val

    return renderer


def _make_bad_renderer():  # type: ignore[no-untyped-def]
    def renderer(df, ticker, news_markers):  # type: ignore[no-untyped-def]
        return "not bytes"

    return renderer


def _noop_loader(ticker: str, window: str):  # type: ignore[no-untyped-def]
    return __import__("pandas").DataFrame()


@pytest.mark.asyncio
async def test_render_kline_returns_png_bytes():
    f = ChartFactory(
        kline_renderer=_make_renderer(_PNG_MAGIC + b"\r\n\x1a\n" + b"X" * 100),
        data_loader=_noop_loader,
    )
    result = await f.render_kline(ChartRequest(ticker="NVDA", kind="kline", window="30d"))
    assert isinstance(result, bytes)
    assert result[:4] == _PNG_MAGIC


@pytest.mark.asyncio
async def test_render_kline_no_data_loader_raises():
    f = ChartFactory(kline_renderer=_make_renderer(_PNG_MAGIC))
    with pytest.raises(RuntimeError, match="no data_loader"):
        await f.render_kline(ChartRequest(ticker="NVDA", kind="kline", window="30d"))


@pytest.mark.asyncio
async def test_render_kline_bad_renderer_raises():
    f = ChartFactory(
        kline_renderer=_make_bad_renderer(),
        data_loader=_noop_loader,
    )
    with pytest.raises(RuntimeError, match="renderer must return bytes"):
        await f.render_kline(ChartRequest(ticker="NVDA", kind="kline", window="30d"))
