# src/news_pipeline/charts/kline.py
from datetime import datetime
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd


def render_kline(
    df: pd.DataFrame,
    *,
    ticker: str,
    news_markers: list[tuple[datetime, str]] | None = None,
    style: str = "yahoo",
) -> bytes:
    addplots = []
    if news_markers:
        marker_series = pd.Series(index=df.index, dtype=float)
        for ts, _ in news_markers:
            ts_norm = pd.Timestamp(ts).normalize()
            if ts_norm in df.index:
                marker_series.loc[ts_norm] = float(df.loc[ts_norm, "High"]) * 1.02
        if marker_series.notna().any():
            addplots.append(
                mpf.make_addplot(
                    marker_series,
                    type="scatter",
                    marker="v",
                    markersize=120,
                    color="red",
                )
            )
    buf = BytesIO()
    fig, _ = mpf.plot(
        df,
        type="candle",
        style=style,
        title=f"{ticker} 30D",
        addplot=addplots if addplots else None,
        returnfig=True,
        volume=True,
        figsize=(8, 6),
    )
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
