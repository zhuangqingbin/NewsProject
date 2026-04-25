# src/news_pipeline/charts/bars.py
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def render_quarterly_bars(
    *,
    quarters: list[str],
    revenue: list[float],
    earnings: list[float],
    ticker: str,
) -> bytes:
    x = np.arange(len(quarters))
    width = 0.4
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x - width / 2, revenue, width, label="Revenue", color="#2c7bb6")
    ax.bar(x + width / 2, earnings, width, label="Earnings", color="#fdae61")
    ax.set_xticks(x)
    ax.set_xticklabels(quarters)
    ax.set_title(f"{ticker} Quarterly Financials")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
