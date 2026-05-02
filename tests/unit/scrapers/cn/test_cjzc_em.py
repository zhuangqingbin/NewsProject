from datetime import UTC, datetime

import pandas as pd
import pytest

from news_pipeline.scrapers.cn.cjzc_em import CjzcEmScraper


def _fake() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "标题": "东方财富财经早餐 4月30日周四",
                "摘要": "1、国务院任命刘浩凌为证监会副主席。",
                "发布时间": "2026-04-30 06:00:59",
                "链接": "http://finance.eastmoney.com/a/202604293725096117.html",
            },
        ]
    )


@pytest.mark.asyncio
async def test_fetch_parses_dataframe():
    s = CjzcEmScraper(news_callable=_fake)
    items = await s.fetch(datetime(2026, 4, 1, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "cjzc_em"
    assert "财经早餐" in items[0].title
