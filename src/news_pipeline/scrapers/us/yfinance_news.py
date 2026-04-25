# src/news_pipeline/scrapers/us/yfinance_news.py
import asyncio
from datetime import UTC, datetime
from typing import Callable, Sequence

import yfinance as yf

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now


class YFinanceNewsScraper:
    source_id = "yfinance_news"
    market = Market.US

    def __init__(
        self,
        *,
        tickers: list[str],
        ticker_factory: Callable[[str], "yf.Ticker"] = yf.Ticker,
    ) -> None:
        self._tickers = tickers
        self._factory = ticker_factory

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        return await asyncio.to_thread(self._fetch_sync, since)

    def _fetch_sync(self, since: datetime) -> list[RawArticle]:
        out: list[RawArticle] = []
        now = utc_now()
        for t in self._tickers:
            ticker = self._factory(t)
            for item in getattr(ticker, "news", []) or []:
                ts = datetime.fromtimestamp(int(item["providerPublishTime"]), tz=UTC)
                if ts < since:
                    continue
                link = item["link"]
                out.append(
                    RawArticle(
                        source=self.source_id,
                        market=self.market,
                        fetched_at=now,
                        published_at=ts,
                        url=link,
                        url_hash=url_hash(link),
                        title=item["title"],
                        title_simhash=title_simhash(item["title"]),
                        body=None,
                        raw_meta={"ticker": t, "publisher": item.get("publisher", "")},
                    )
                )
        return out
