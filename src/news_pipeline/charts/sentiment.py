# src/news_pipeline/charts/sentiment.py
from datetime import datetime
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt


def render_sentiment_curve(
    *,
    points: list[tuple[datetime, float]],
    ticker: str,
) -> bytes:
    if not points:
        raise ValueError("no points")
    xs, ys = zip(*sorted(points), strict=False)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(xs, ys, marker="o", color="#2c7bb6")
    ax.axhline(0.0, color="#888", linewidth=0.5)
    ax.set_ylim(-1.0, 1.0)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.set_title(f"{ticker} Sentiment (1=bullish, -1=bearish)")
    ax.grid(True, alpha=0.3)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
