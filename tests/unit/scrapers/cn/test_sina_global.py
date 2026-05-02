from datetime import UTC, datetime

import pandas as pd
import pytest

from news_pipeline.scrapers.cn.sina_global import SinaGlobalScraper


def _fake() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "时间": "2026-05-02 18:10:03",
                "内容": "瑞典一集会活动发生爆炸 致3人受伤",
            },
            {
                "时间": "2026-05-02 18:11:00",
                "内容": "",  # empty body → skipped
            },
        ]
    )


@pytest.mark.asyncio
async def test_fetch_parses_dataframe():
    s = SinaGlobalScraper(news_callable=_fake)
    items = await s.fetch(datetime(2026, 5, 1, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "sina_global"
    # synthesized URL must be a real https one for HttpUrl validation
    assert str(items[0].url).startswith("https://finance.sina.com.cn/7x24/")
