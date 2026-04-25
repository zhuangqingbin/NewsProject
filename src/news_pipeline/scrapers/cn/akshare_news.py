# src/news_pipeline/scrapers/cn/akshare_news.py
import asyncio
from datetime import UTC, datetime
from typing import Callable, Sequence

import akshare as ak
import pandas as pd

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import ensure_utc, utc_now


class AkshareNewsScraper:
    source_id = "akshare_news"
    market = Market.CN

    def __init__(
        self,
        *,
        tickers: list[str],
        news_callable: Callable[[str], pd.DataFrame] = ak.stock_news_em,
    ) -> None:
        self._tickers = tickers
        self._news_callable = news_callable

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        return await asyncio.to_thread(self._fetch_sync, since)

    def _fetch_sync(self, since: datetime) -> list[RawArticle]:
        out: list[RawArticle] = []
        now = utc_now()
        for t in self._tickers:
            df = self._news_callable(t)
            for _, row in df.iterrows():
                pub = pd.to_datetime(row.get("发布时间")).tz_localize("Asia/Shanghai")
                ts = ensure_utc(pub.to_pydatetime())
                if ts < since:
                    continue
                link = str(row.get("链接") or row.get("文章链接") or "")
                if not link:
                    continue
                title = str(row.get("标题") or row.get("新闻标题") or "")
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
                        body=str(row.get("内容") or row.get("新闻内容") or "") or None,
                        raw_meta={"ticker": t},
                    )
                )
        return out
