# tests/unit/scrapers/cn/test_eastmoney_global.py
from datetime import UTC, datetime

import pandas as pd
import pytest

from news_pipeline.scrapers.cn.eastmoney_global import EastmoneyGlobalScraper


def _fake_em() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "标题": "创业板指半日跌0.54%",
                "摘要": "市场早盘震荡调整。",
                "发布时间": "2026-04-28 11:32:29",
                "链接": "https://finance.eastmoney.com/a/abc.html",
            },
            {
                "标题": "",  # missing title AND empty body → skipped
                "摘要": "",
                "发布时间": "2026-04-28 11:30:00",
                "链接": "https://finance.eastmoney.com/a/x.html",
            },
        ]
    )


@pytest.mark.asyncio
async def test_fetch_parses_dataframe():
    s = EastmoneyGlobalScraper(news_callable=_fake_em)
    items = await s.fetch(datetime(2026, 4, 1, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "eastmoney_global"
    assert items[0].title == "创业板指半日跌0.54%"
    assert str(items[0].url).startswith("https://finance.eastmoney.com/")


@pytest.mark.asyncio
async def test_since_filter_skips_old():
    s = EastmoneyGlobalScraper(news_callable=_fake_em)
    items = await s.fetch(datetime(2026, 4, 28, 12, 0, tzinfo=UTC))
    assert len(items) == 0
