# tests/unit/scrapers/cn/test_ths.py
from datetime import UTC, datetime

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


@pytest.mark.asyncio
async def test_anticrawl_login_page():
    """200 response body containing '登录' (login prompt) raises AntiCrawlError."""
    from news_pipeline.common.exceptions import AntiCrawlError

    login_html = "<html><body>请先登录才能继续访问</body></html>"
    async with respx.mock() as mock:
        mock.get(url__regex=r"https?://news\.10jqka\.com\.cn/.*").mock(
            return_value=Response(200, text=login_html)
        )
        s = ThsScraper(tickers=["600519"], cookie="x=1")
        with pytest.raises(AntiCrawlError, match="login/captcha"):
            await s.fetch(datetime(2024, 4, 1, tzinfo=UTC))


@pytest.mark.asyncio
async def test_anticrawl_empty_body():
    """200 response with empty body raises AntiCrawlError (silent failure mode)."""
    from news_pipeline.common.exceptions import AntiCrawlError

    async with respx.mock() as mock:
        mock.get(url__regex=r"https?://news\.10jqka\.com\.cn/.*").mock(
            return_value=Response(200, text="")
        )
        s = ThsScraper(tickers=["600519"], cookie="x=1")
        with pytest.raises(AntiCrawlError, match="empty body"):
            await s.fetch(datetime(2024, 4, 1, tzinfo=UTC))
