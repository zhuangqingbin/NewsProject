# tests/unit/scrapers/cn/test_caixin_telegram.py
from datetime import UTC, datetime

import pytest
import respx
from httpx import Response

from news_pipeline.scrapers.cn.caixin_telegram import CaixinTelegramScraper

SAMPLE = {
    "data": {
        "roll_data": [
            {
                "id": 1,
                "title": "央行降准",
                "brief": "降准0.5%",
                "ctime": 1714000000,
                "shareurl": "https://www.cls.cn/d/1",
            },
            {
                "id": 2,
                "title": "茅台一季报",
                "brief": "营收+20%",
                "ctime": 1714000500,
                "shareurl": "https://www.cls.cn/d/2",
            },
        ]
    }
}


@pytest.mark.asyncio
async def test_fetch_parses_roll():
    async with respx.mock() as mock:
        mock.get(url__regex=r"https://www\.cls\.cn/v3/.*").mock(
            return_value=Response(200, json=SAMPLE)
        )
        s = CaixinTelegramScraper()
        items = await s.fetch(datetime(2024, 1, 1, tzinfo=UTC))
        assert len(items) == 2
        assert items[0].source == "caixin_telegram"
