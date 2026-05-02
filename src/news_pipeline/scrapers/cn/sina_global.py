"""新浪财经全球财经快讯.

DataFrame schema differs from the others — only `[时间, 内容]`, no link, no
title — so we synthesize a stable https URL the same way caixin_telegram
does, and derive the title from the body excerpt.
"""

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


class SinaGlobalScraper:
    source_id = "sina_global"
    market = Market.CN

    def __init__(
        self,
        *,
        news_callable: Callable[[], pd.DataFrame] = ak.stock_info_global_sina,
    ) -> None:
        self._news_callable = news_callable

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        return await asyncio.to_thread(self._fetch_sync, since)

    def _fetch_sync(self, since: datetime) -> list[RawArticle]:
        df = self._news_callable()
        out: list[RawArticle] = []
        now = utc_now()
        for _, row in df.iterrows():
            pub_str = row.get("时间")
            if not pub_str:
                continue
            local = pd.Timestamp(pub_str).tz_localize("Asia/Shanghai")
            ts = ensure_utc(local.to_pydatetime())
            if ts < since:
                continue
            body = (row.get("内容") or "").strip()
            if not body:
                continue
            # Sina quick news has no canonical URL — synthesize a stable one.
            digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]
            link = f"https://finance.sina.com.cn/7x24/{ts.strftime('%Y%m%dT%H%M%S')}/{digest}"
            title = body[:80]
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
                    raw_meta={"provider": "akshare_sina"},
                )
            )
        return out
