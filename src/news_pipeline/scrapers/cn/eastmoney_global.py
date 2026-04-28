# src/news_pipeline/scrapers/cn/eastmoney_global.py
import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime

import akshare as ak
import pandas as pd

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import ensure_utc, utc_now


class EastmoneyGlobalScraper:
    """东方财富全球财经快讯 — broad CN market wire, not bound to any ticker.

    Returns ~200 most-recent items per call, with real article URLs. Acts as
    the primary general-news source so the rules engine has material to match
    macro/sector keywords against.
    """

    source_id = "eastmoney_global"
    market = Market.CN

    def __init__(
        self,
        *,
        news_callable: Callable[[], pd.DataFrame] = ak.stock_info_global_em,
    ) -> None:
        self._news_callable = news_callable

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        return await asyncio.to_thread(self._fetch_sync, since)

    def _fetch_sync(self, since: datetime) -> list[RawArticle]:
        df = self._news_callable()
        out: list[RawArticle] = []
        now = utc_now()
        for _, row in df.iterrows():
            pub_str = row.get("发布时间")
            if not pub_str:
                continue
            local = pd.Timestamp(pub_str).tz_localize("Asia/Shanghai")
            ts = ensure_utc(local.to_pydatetime())
            if ts < since:
                continue
            link = (row.get("链接") or "").strip()
            title = (row.get("标题") or "").strip()
            if not link or not title:
                continue
            body = (row.get("摘要") or "").strip() or None
            out.append(
                RawArticle(
                    source=self.source_id,
                    market=self.market,
                    fetched_at=now,
                    published_at=ts,
                    url=link,
                    url_hash=url_hash(link),
                    title=title,
                    title_simhash=title_simhash(title),
                    body=body,
                    raw_meta={"provider": "akshare_em"},
                )
            )
        return out
