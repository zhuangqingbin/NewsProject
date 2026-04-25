# src/news_pipeline/charts/factory.py
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class ChartRequest:
    ticker: str
    kind: str  # kline | bars | sentiment
    window: str  # "30d" | "1y" | etc.
    params: dict[str, Any] = field(default_factory=dict)

    def request_hash(self) -> str:
        s = f"{self.ticker}|{self.kind}|{self.window}|{sorted(self.params.items())}"
        return hashlib.sha1(s.encode()).hexdigest()[:16]


class ChartFactory:
    def __init__(
        self,
        *,
        kline_renderer: Callable[..., bytes],
        data_loader: Callable[[str, str], pd.DataFrame] | None = None,
    ) -> None:
        self._render_kline = kline_renderer
        self._data_loader = data_loader

    async def render_kline(self, req: ChartRequest) -> bytes:
        """Render a kline chart and return raw PNG bytes for inline embedding."""
        if self._data_loader is None:
            raise RuntimeError("no data_loader configured")
        df = self._data_loader(req.ticker, req.window)
        png = self._render_kline(df, ticker=req.ticker, news_markers=None)
        if not isinstance(png, bytes):
            raise RuntimeError("renderer must return bytes")
        return png
