from datetime import UTC, datetime

import pandas as pd
import pytest

from news_pipeline.scrapers.cn.cctv_news import CctvNewsScraper


def _fake(date: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": date, "title": "习近平会见外宾", "content": "正文内容。"},
            {"date": date, "title": "", "content": "no title"},  # skipped
        ]
    )


@pytest.mark.asyncio
async def test_fetch_parses_dataframe():
    s = CctvNewsScraper(news_callable=_fake)
    # since well in the past so today's broadcast passes the filter
    items = await s.fetch(datetime(2020, 1, 1, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "cctv_news"
    assert items[0].title == "习近平会见外宾"
