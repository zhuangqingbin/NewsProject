# tests/unit/scrapers/us/test_yfinance_news.py
from datetime import UTC, datetime

import pytest

from news_pipeline.scrapers.us.yfinance_news import YFinanceNewsScraper


class _FakeTicker:
    def __init__(self, news):
        self.news = news


def _factory(news_per_ticker):
    def make(ticker):
        return _FakeTicker(news_per_ticker.get(ticker, []))

    return make


@pytest.mark.asyncio
async def test_fetch_parses_news():
    news = {
        "NVDA": [
            {
                "title": "NVDA up",
                "link": "https://yhoo/1",
                "providerPublishTime": 1714000000,
                "publisher": "Yahoo",
            }
        ]
    }
    s = YFinanceNewsScraper(tickers=["NVDA"], ticker_factory=_factory(news))
    items = await s.fetch(datetime(2024, 1, 1, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "yfinance_news"


@pytest.mark.asyncio
async def test_fetch_skips_old():
    news = {
        "NVDA": [
            {
                "title": "old",
                "link": "https://yhoo/1",
                "providerPublishTime": 1614000000,
                "publisher": "Yahoo",
            }
        ]
    }
    s = YFinanceNewsScraper(tickers=["NVDA"], ticker_factory=_factory(news))
    items = await s.fetch(datetime(2026, 4, 25, tzinfo=UTC))
    assert items == []
