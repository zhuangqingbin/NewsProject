# src/news_pipeline/charts/factory.py
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from news_pipeline.charts.uploader import OSSUploader
from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.dao.chart_cache import ChartCacheDAO


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
        cache_dao: ChartCacheDAO,
        kline_renderer: Callable[..., bytes],
        uploader: OSSUploader,
        data_loader: Callable[[str, str], pd.DataFrame] | None = None,
        ttl_days: int = 30,
    ) -> None:
        self._cache = cache_dao
        self._render_kline = kline_renderer
        self._uploader = uploader
        self._data_loader = data_loader
        self._ttl_days = ttl_days

    async def render_kline(self, req: ChartRequest) -> str:
        cached = await self._cache.get(req.request_hash())
        if cached is not None:
            return cached.oss_url
        if self._data_loader is None:
            raise RuntimeError("no data_loader configured")
        df = self._data_loader(req.ticker, req.window)
        png = self._render_kline(df, ticker=req.ticker, news_markers=None)
        if not isinstance(png, bytes):
            raise RuntimeError("renderer must return bytes")
        ts = utc_now()
        path = (
            f"charts/{ts.year}/{ts.month:02d}/{ts.day:02d}/"
            f"{req.ticker}_{req.kind}_{req.request_hash()}.png"
        )
        url = self._uploader.upload(path_in_bucket=path, content=png)
        await self._cache.put(
            request_hash=req.request_hash(),
            ticker=req.ticker,
            kind=req.kind,
            oss_url=url,
            ttl_days=self._ttl_days,
        )
        return url
