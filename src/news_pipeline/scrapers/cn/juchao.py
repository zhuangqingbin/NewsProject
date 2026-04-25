# src/news_pipeline/scrapers/cn/juchao.py
from collections.abc import Sequence
from datetime import UTC, datetime

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.http import make_async_client


class JuchaoScraper:
    source_id = "juchao"
    market = Market.CN

    def __init__(self, *, tickers: list[str]) -> None:
        self._tickers = tickers

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
        out: list[RawArticle] = []
        now = utc_now()
        async with make_async_client() as client:
            for ticker in self._tickers:
                form = {
                    "stock": ticker,
                    "tabName": "fulltext",
                    "pageSize": 30,
                    "pageNum": 1,
                }
                resp = await client.post(url, data=form)
                resp.raise_for_status()
                for ann in resp.json().get("announcements") or []:
                    ts = datetime.fromtimestamp(
                        int(ann["announcementTime"]) / 1000, tz=UTC
                    )
                    if ts < since:
                        continue
                    link = "http://static.cninfo.com.cn/" + ann["adjunctUrl"]
                    title = f'{ann["secName"]} {ann["announcementTitle"]}'
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
                            body=None,
                            raw_meta={
                                "ann_id": ann["announcementId"],
                                "code": ann["secCode"],
                            },
                        )
                    )
        return out
