# tests/unit/scrapers/cn/test_ths.py
from datetime import datetime, UTC

import pytest
import respx
from httpx import Response

from news_pipeline.scrapers.cn.ths import ThsScraper


SAMPLE_HTML = """
<html><body>
<div class="news-list">
  <a class="news-link" href="/news/1.html" data-time="1714000000">
    <span class="news-title">茅台分红</span>
  </a>
</div>
</body></html>
"""


@pytest.mark.asyncio
async def test_fetch_parses():
    async with respx.mock() as mock:
        mock.get(url__regex=r"https?://news\.10jqka\.com\.cn/.*").mock(
            return_value=Response(200, text=SAMPLE_HTML)
        )
        s = ThsScraper(tickers=["600519"], cookie="x=1")
        items = await s.fetch(datetime(2024, 4, 1, tzinfo=UTC))
        assert len(items) == 1


@pytest.mark.asyncio
async def test_anticrawl_raises():
    from news_pipeline.common.exceptions import AntiCrawlError
    async with respx.mock() as mock:
        mock.get(url__regex=r"https?://news\.10jqka\.com\.cn/.*").mock(
            return_value=Response(403, text="")
        )
        s = ThsScraper(tickers=["600519"], cookie="x=1")
        with pytest.raises(AntiCrawlError):
            await s.fetch(datetime(2024, 4, 1, tzinfo=UTC))
