# src/news_pipeline/scrapers/us/sec_edgar.py
from collections.abc import Sequence
from datetime import UTC, datetime

import feedparser

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.http import make_async_client


class SecEdgarScraper:
    source_id = "sec_edgar"
    market = Market.US

    def __init__(self, *, ciks: list[str]) -> None:
        self._ciks = ciks

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        out: list[RawArticle] = []
        now = utc_now()
        async with make_async_client() as client:
            for cik in self._ciks:
                url = (
                    "https://www.sec.gov/cgi-bin/browse-edgar"
                    f"?action=getcompany&CIK={cik}"
                    "&type=&dateb=&owner=include&count=20&output=atom"
                )
                resp = await client.get(
                    url, headers={"User-Agent": "news-pipeline qingbin@example.com"}
                )
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
                for e in feed.entries:
                    ts = datetime(*e.updated_parsed[:6], tzinfo=UTC)
                    if ts < since:
                        continue
                    link = e.link
                    out.append(
                        RawArticle(
                            source=self.source_id,
                            market=self.market,
                            fetched_at=now,
                            published_at=ts,
                            url=link,
                            url_hash=url_hash(link),
                            title=e.title,
                            title_simhash=title_simhash(e.title),
                            body=getattr(e, "summary", None),
                            raw_meta={"cik": cik, "id": e.id},
                        )
                    )
        return out
