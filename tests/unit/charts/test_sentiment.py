# tests/unit/charts/test_sentiment.py
from datetime import datetime, timedelta

from news_pipeline.charts.sentiment import render_sentiment_curve


def test_render_returns_png():
    today = datetime(2026, 4, 25)
    points = [(today - timedelta(days=i), 0.5 + (i % 3 - 1) * 0.2) for i in range(7, 0, -1)]
    png = render_sentiment_curve(points=points, ticker="NVDA")
    assert isinstance(png, bytes) and png[:8] == b"\x89PNG\r\n\x1a\n"
