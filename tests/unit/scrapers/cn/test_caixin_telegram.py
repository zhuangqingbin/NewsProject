# tests/unit/scrapers/cn/test_caixin_telegram.py
from datetime import UTC, date, datetime, time

import pandas as pd
import pytest

from news_pipeline.scrapers.cn.caixin_telegram import CaixinTelegramScraper


def _fake_cls(symbol: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "标题": "央行降准0.5%",
                "内容": "央行宣布降准",
                "发布日期": date(2026, 4, 28),
                "发布时间": time(11, 0, 0),
            },
            {
                "标题": "",
                "内容": "茅台一季报营收同比+20%",
                "发布日期": date(2026, 4, 28),
                "发布时间": time(11, 5, 0),
            },
        ]
    )


@pytest.mark.asyncio
async def test_fetch_parses_dataframe():
    s = CaixinTelegramScraper(news_callable=_fake_cls)
    items = await s.fetch(datetime(2026, 4, 1, tzinfo=UTC))
    assert len(items) == 2
    assert items[0].source == "caixin_telegram"
    assert items[0].title == "央行降准0.5%"
    # second item has empty title — falls back to body excerpt
    assert items[1].title.startswith("茅台一季报")
    # synthesized URL must be https for HttpUrl validation
    assert str(items[0].url).startswith("https://www.cls.cn/telegraph/")


@pytest.mark.asyncio
async def test_since_filter_skips_old():
    s = CaixinTelegramScraper(news_callable=_fake_cls)
    # since after both items' published_at
    items = await s.fetch(datetime(2026, 4, 28, 12, 0, tzinfo=UTC))
    assert len(items) == 0
