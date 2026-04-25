# tests/unit/scrapers/cn/test_juchao.py
from datetime import UTC, datetime

import pytest
import respx
from httpx import Response

from news_pipeline.scrapers.cn.juchao import JuchaoScraper

SAMPLE = {
    "announcements": [
        {
            "announcementId": "100",
            "announcementTitle": "茅台2026Q1 财报",
            "announcementTime": 1714000000000,
            "adjunctUrl": "finalpage/2026-04-25/x.PDF",
            "secCode": "600519",
            "secName": "贵州茅台",
        }
    ]
}


@pytest.mark.asyncio
async def test_fetch_parses():
    async with respx.mock() as mock:
        mock.post("http://www.cninfo.com.cn/new/hisAnnouncement/query").mock(
            return_value=Response(200, json=SAMPLE)
        )
        s = JuchaoScraper(tickers=["600519"])
        items = await s.fetch(datetime(2024, 1, 1, tzinfo=UTC))
        assert len(items) == 1
        assert "茅台" in items[0].title
