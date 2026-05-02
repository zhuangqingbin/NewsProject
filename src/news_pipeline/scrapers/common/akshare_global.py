"""Shared base for akshare-backed global news scrapers.

These all share the same DataFrame shape `[标题, 内容|摘要, 发布时间, 链接]`
returned by akshare's `stock_info_global_*` family. Subclasses just set
class-level metadata + which column holds the body text.
"""

import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime

import pandas as pd

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import ensure_utc, utc_now


class AkshareGlobalScraper:
    source_id: str = "<override>"
    market: Market = Market.CN
    body_col: str = "内容"  # some sources use 摘要

    def __init__(self, *, news_callable: Callable[[], pd.DataFrame]) -> None:
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
            body = (row.get(self.body_col) or "").strip()
            title = (row.get("标题") or "").strip() or body[:80]
            if not link or not title:
                continue
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
                    body=body or None,
                    raw_meta={"provider": f"akshare_{self.source_id}"},
                )
            )
        return out
