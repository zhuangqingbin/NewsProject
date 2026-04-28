# src/news_pipeline/scrapers/cn/caixin_telegram.py
import asyncio
import hashlib
from collections.abc import Callable, Sequence
from datetime import datetime

import akshare as ak
import pandas as pd

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import ensure_utc, utc_now


class CaixinTelegramScraper:
    """财联社快讯 (CLS Telegraph).

    Uses akshare's stock_info_global_cls under the hood — akshare handles the
    request-signing CLS now requires, so we don't reinvent that wheel.
    """

    source_id = "caixin_telegram"
    market = Market.CN

    def __init__(
        self,
        *,
        symbol: str = "全部",
        news_callable: Callable[[str], pd.DataFrame] = ak.stock_info_global_cls,
    ) -> None:
        self._symbol = symbol
        self._news_callable = news_callable

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        return await asyncio.to_thread(self._fetch_sync, since)

    def _fetch_sync(self, since: datetime) -> list[RawArticle]:
        df = self._news_callable(self._symbol)
        out: list[RawArticle] = []
        now = utc_now()
        for _, row in df.iterrows():
            date_part = row.get("发布日期")
            time_part = row.get("发布时间")
            if date_part is None or time_part is None:
                continue
            local = pd.Timestamp.combine(date_part, time_part).tz_localize("Asia/Shanghai")
            ts = ensure_utc(local.to_pydatetime())
            if ts < since:
                continue
            title = (row.get("标题") or "").strip()
            body = (row.get("内容") or "").strip()
            display_title = title or body[:80]
            if not display_title:
                continue
            # CLS quick news has no canonical URL — synthesize a stable https
            # one from timestamp + title hash. Pydantic HttpUrl rejects custom
            # schemes; the URL only needs to be unique for dedup.
            digest = hashlib.sha1(display_title.encode("utf-8")).hexdigest()[:12]
            link = f"https://www.cls.cn/telegraph/{ts.strftime('%Y%m%dT%H%M%S')}/{digest}"
            out.append(
                RawArticle(
                    source=self.source_id,
                    market=self.market,
                    fetched_at=now,
                    published_at=ts,
                    url=link,
                    url_hash=url_hash(link),
                    title=display_title,
                    title_simhash=title_simhash(display_title),
                    body=body or None,
                    raw_meta={"provider": "akshare_cls"},
                )
            )
        return out
