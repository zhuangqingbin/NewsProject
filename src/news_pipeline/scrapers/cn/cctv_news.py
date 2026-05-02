"""新闻联播文字稿 (CCTV evening broadcast transcript).

Once-daily after 19:30 Beijing. Returns ~14 segments per day. URL is
synthesized from CCTV's standard archive pattern. Date arg required by
akshare; we derive it from `since` (today's Beijing date).
"""

import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import ensure_utc, utc_now


class CctvNewsScraper:
    source_id = "cctv_news"
    market = Market.CN

    def __init__(
        self,
        *,
        news_callable: Callable[[str], pd.DataFrame] = ak.news_cctv,
    ) -> None:
        self._news_callable = news_callable

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        return await asyncio.to_thread(self._fetch_sync, since)

    def _fetch_sync(self, since: datetime) -> list[RawArticle]:
        # Always pull yesterday's broadcast (date in akshare is YYYYMMDD).
        # CCTV publishes after 19:30 CST; yesterday's transcript is the
        # most recent guaranteed-complete one whenever this job runs.
        beijing_yesterday = (utc_now() + timedelta(hours=8) - timedelta(days=1)).date()
        date_str = beijing_yesterday.strftime("%Y%m%d")
        df = self._news_callable(date_str)
        out: list[RawArticle] = []
        now = utc_now()
        # Treat the broadcast as published at 19:30 Beijing on `date_str`.
        local = pd.Timestamp(f"{beijing_yesterday} 19:30:00").tz_localize("Asia/Shanghai")
        ts = ensure_utc(local.to_pydatetime())
        if ts < since:
            return out
        for idx, row in df.iterrows():
            title = (row.get("title") or "").strip()
            body = (row.get("content") or "").strip()
            if not title:
                continue
            link = f"https://tv.cctv.com/lm/xwlb/day/{date_str}.shtml#seg{idx}"
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
                    raw_meta={"provider": "akshare_cctv", "date": date_str},
                )
            )
        return out
