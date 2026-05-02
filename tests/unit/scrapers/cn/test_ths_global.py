from datetime import UTC, datetime

import pandas as pd
import pytest

from news_pipeline.scrapers.cn.ths_global import ThsGlobalScraper


def _fake() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "标题": "瑞典一集会活动发生爆炸",
                "内容": "已致3人受伤。",
                "发布时间": "2026-05-02 18:09:58",
                "链接": "https://news.10jqka.com.cn/20260502/c676442815.shtml",
            },
        ]
    )


@pytest.mark.asyncio
async def test_fetch_parses_dataframe():
    s = ThsGlobalScraper(news_callable=_fake)
    items = await s.fetch(datetime(2026, 5, 1, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "ths_global"
    assert items[0].title.startswith("瑞典")


@pytest.mark.asyncio
async def test_since_filter_skips_old():
    s = ThsGlobalScraper(news_callable=_fake)
    items = await s.fetch(datetime(2026, 5, 3, tzinfo=UTC))
    assert len(items) == 0
