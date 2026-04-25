# tests/unit/charts/test_kline.py
from datetime import datetime

import pandas as pd

from news_pipeline.charts.kline import render_kline


def _ohlc_df() -> pd.DataFrame:
    # Use a Monday end date so freq="B" gives exactly `periods` entries
    idx = pd.date_range(end=datetime(2026, 4, 27), periods=30, freq="B")
    n = len(idx)
    return pd.DataFrame(
        {
            "Open": [100 + i * 0.5 for i in range(n)],
            "High": [101 + i * 0.5 for i in range(n)],
            "Low": [99 + i * 0.5 for i in range(n)],
            "Close": [100.5 + i * 0.5 for i in range(n)],
            "Volume": [1000] * n,
        },
        index=idx,
    )


def test_render_kline_returns_png_bytes():
    df = _ohlc_df()
    markers = [(df.index[-3], "🔴")]
    png = render_kline(df, ticker="NVDA", news_markers=markers)
    assert isinstance(png, bytes)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
