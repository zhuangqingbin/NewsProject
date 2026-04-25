# tests/unit/scrapers/us/test_finnhub.py
from datetime import UTC, datetime

import pytest
import respx
from httpx import Response

from news_pipeline.scrapers.us.finnhub import FinnhubScraper


@pytest.mark.asyncio
async def test_fetch_parses_articles():
    sample = [
        {
            "id": 1,
            "headline": "NVDA beats",
            "summary": "summary",
            "source": "Reuters",
            "url": "https://reut.com/a",
            "datetime": 1714000000,
            "image": "",
        },
        {
            "id": 2,
            "headline": "TSLA news",
            "summary": "...",
            "source": "Bloomberg",
            "url": "https://bberg.com/b",
            "datetime": 1714000500,
            "image": "",
        },
    ]
    async with respx.mock(assert_all_called=True) as mock:
        mock.get("https://finnhub.io/api/v1/news").mock(return_value=Response(200, json=sample))
        scraper = FinnhubScraper(token="t1", tickers=["NVDA"], category="general")
        # timestamps 1714000000 ≈ 2024-04-25; use since before that
        items = await scraper.fetch(datetime(2024, 1, 1, tzinfo=UTC))
        assert len(items) == 2
        assert items[0].source == "finnhub"
        assert str(items[0].url) == "https://reut.com/a"
        assert items[0].title == "NVDA beats"


@pytest.mark.asyncio
async def test_fetch_skips_old_items():
    sample = [
        {
            "id": 1,
            "headline": "old",
            "summary": "",
            "source": "x",
            "url": "https://x/1",
            "datetime": 1714000000,
            "image": "",
        },
    ]
    async with respx.mock() as mock:
        mock.get("https://finnhub.io/api/v1/news").mock(return_value=Response(200, json=sample))
        scraper = FinnhubScraper(token="t1", tickers=[], category="general")
        items = await scraper.fetch(datetime(2030, 1, 1, tzinfo=UTC))
        assert items == []
