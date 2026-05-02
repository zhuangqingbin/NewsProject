from datetime import UTC, datetime

import pandas as pd
import pytest

from news_pipeline.scrapers.us.futu_global import FutuGlobalScraper


def _fake() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "标题": "",  # futu often has empty title
                "内容": "地中海航运公司宣布推出新的欧洲-红海-中东快递服务。",
                "发布时间": "2026-05-02 17:37:43",
                "链接": "https://news.futunn.com/flash/20250056/abc",
            },
        ]
    )


@pytest.mark.asyncio
async def test_fetch_parses_dataframe():
    s = FutuGlobalScraper(news_callable=_fake)
    items = await s.fetch(datetime(2026, 5, 1, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "futu_global"
    # title falls back to body excerpt when missing
    assert items[0].title.startswith("地中海航运公司")
