# tests/unit/scrapers/cn/test_akshare_news.py
from datetime import UTC, datetime

import pandas as pd
import pytest

from news_pipeline.scrapers.cn.akshare_news import AkshareNewsScraper


def _fake_news(symbol: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "标题": "茅台公告分红",
                "发布时间": "2026-04-25 14:00:00",
                "链接": "https://eastmoney/x",
            }
        ]
    )


@pytest.mark.asyncio
async def test_fetch_parses_dataframe():
    s = AkshareNewsScraper(tickers=["600519"], news_callable=_fake_news)
    items = await s.fetch(datetime(2026, 4, 25, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "akshare_news"
