# tests/unit/scrapers/cn/test_xueqiu.py
from datetime import UTC, datetime

import pytest
import respx
from httpx import Response

from news_pipeline.scrapers.cn.xueqiu import XueqiuScraper

SAMPLE = {
    "list": [
        {
            "id": 1,
            "title": "雪球热议NVDA",
            "target": "/S/SH600519/123",
            "created_at": 1714000000000,
            "description": "讨论",
        }
    ]
}


@pytest.mark.asyncio
async def test_fetch_parses():
    async with respx.mock() as mock:
        mock.get(url__regex=r"https://xueqiu\.com/.*").mock(return_value=Response(200, json=SAMPLE))
        s = XueqiuScraper(tickers=["600519"], cookie="x=1")
        items = await s.fetch(datetime(2024, 4, 1, tzinfo=UTC))
        assert len(items) == 1


@pytest.mark.asyncio
async def test_anticrawl_raises():
    from news_pipeline.common.exceptions import AntiCrawlError

    async with respx.mock() as mock:
        mock.get(url__regex=r"https://xueqiu\.com/.*").mock(
            return_value=Response(403, text="forbidden")
        )
        s = XueqiuScraper(tickers=["600519"], cookie="x=1")
        with pytest.raises(AntiCrawlError):
            await s.fetch(datetime(2024, 4, 1, tzinfo=UTC))
