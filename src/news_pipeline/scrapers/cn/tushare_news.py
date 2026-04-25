# src/news_pipeline/scrapers/cn/tushare_news.py
import asyncio
import hashlib
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

import pandas as pd

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import ensure_utc, utc_now


def _default_pro_factory() -> object:
    import tushare as ts

    return ts.pro_api()


class TushareNewsScraper:
    source_id = "tushare_news"
    market = Market.CN

    def __init__(
        self,
        *,
        src: str = "sina",
        pro_factory: Callable[[], object] = _default_pro_factory,
    ) -> None:
        self._src = src
        self._pro_factory = pro_factory

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        return await asyncio.to_thread(self._fetch_sync, since)

    def _fetch_sync(self, since: datetime) -> list[RawArticle]:
        pro = self._pro_factory()
        end = utc_now()
        start = end - timedelta(hours=1)
        df: pd.DataFrame = pro.news(  # type: ignore[attr-defined]
            src=self._src,
            start_date=start.strftime("%Y-%m-%d %H:%M:%S"),
            end_date=end.strftime("%Y-%m-%d %H:%M:%S"),
        )
        out: list[RawArticle] = []
        now = utc_now()
        for _, row in df.iterrows():
            ts = pd.to_datetime(row["datetime"]).tz_localize("Asia/Shanghai")
            ts = ensure_utc(ts.to_pydatetime())
            if ts < since:
                continue
            title = str(row.get("title") or row["content"][:60])
            content = str(row["content"])
            # Synthetic URL since tushare API doesn't always provide one
            synthetic = f"https://tushare.local/{self._src}/" + hashlib.sha1(
                (str(row["datetime"]) + content).encode()
            ).hexdigest()[:16]
            out.append(
                RawArticle(
                    source=self.source_id,
                    market=self.market,
                    fetched_at=now,
                    published_at=ts,
                    url=synthetic,
                    url_hash=url_hash(synthetic),
                    title=title,
                    title_simhash=title_simhash(title),
                    body=content,
                    raw_meta={"src": self._src},
                )
            )
        return out
