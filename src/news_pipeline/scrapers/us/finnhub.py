# src/news_pipeline/scrapers/us/finnhub.py
from collections.abc import Sequence
from datetime import UTC, datetime

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.http import make_async_client


class FinnhubScraper:
    source_id = "finnhub"
    market = Market.US

    def __init__(
        self, *, token: str, tickers: list[str], category: str = "general"
    ) -> None:
        self._token = token
        self._tickers = tickers
        self._category = category

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        url = "https://finnhub.io/api/v1/news"
        params = {"category": self._category, "token": self._token}
        async with make_async_client() as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        out: list[RawArticle] = []
        now = utc_now()
        for item in data:
            ts = datetime.fromtimestamp(int(item["datetime"]), tz=UTC)
            if ts < since:
                continue
            link = item["url"]
            out.append(
                RawArticle(
                    source=self.source_id,
                    market=self.market,
                    fetched_at=now,
                    published_at=ts,
                    url=link,
                    url_hash=url_hash(link),
                    title=item["headline"],
                    title_simhash=title_simhash(item["headline"]),
                    body=item.get("summary"),
                    raw_meta={"finnhub_id": item["id"], "source": item["source"]},
                )
            )
        return out
