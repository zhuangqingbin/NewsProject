# tests/unit/charts/test_bars.py
from news_pipeline.charts.bars import render_quarterly_bars


def test_render_returns_png_bytes():
    quarters = ["Q1 25", "Q2 25", "Q3 25", "Q4 25", "Q1 26"]
    revenue = [100, 110, 120, 130, 145]
    earnings = [10, 12, 13, 15, 18]
    png = render_quarterly_bars(
        quarters=quarters,
        revenue=revenue,
        earnings=earnings,
        ticker="NVDA",
    )
    assert isinstance(png, bytes) and png[:8] == b"\x89PNG\r\n\x1a\n"
