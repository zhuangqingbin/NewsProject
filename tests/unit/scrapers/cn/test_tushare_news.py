# tests/unit/scrapers/cn/test_tushare_news.py
from datetime import datetime, UTC

import pandas as pd
import pytest

from news_pipeline.scrapers.cn.tushare_news import TushareNewsScraper


class _FakePro:
    def news(self, src: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame([
            {"datetime": "2026-04-25 14:00:00", "content": "上证大涨", "title": "市场观察"}
        ])


@pytest.mark.asyncio
async def test_fetch_parses():
    s = TushareNewsScraper(pro_factory=lambda: _FakePro(), src="sina")
    items = await s.fetch(datetime(2026, 4, 25, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "tushare_news"
