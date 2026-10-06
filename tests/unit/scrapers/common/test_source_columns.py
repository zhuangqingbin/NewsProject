from datetime import UTC, datetime

import pandas as pd
import pytest

from news_pipeline.scrapers.cn.cctv_news import CctvNewsScraper
from news_pipeline.scrapers.cn.cjzc_em import CjzcEmScraper
from news_pipeline.scrapers.cn.eastmoney_global import EastmoneyGlobalScraper
from news_pipeline.scrapers.cn.sina_global import SinaGlobalScraper
from news_pipeline.scrapers.cn.ths_global import ThsGlobalScraper
from news_pipeline.scrapers.common.contract import SourceContractError
from news_pipeline.scrapers.us.futu_global import FutuGlobalScraper


@pytest.mark.parametrize(
    "scraper",
    [
        EastmoneyGlobalScraper,
        ThsGlobalScraper,
        FutuGlobalScraper,
        SinaGlobalScraper,
        CjzcEmScraper,
        CctvNewsScraper,
    ],
)
async def test_missing_columns_fail_even_on_empty_dataframe(scraper):
    source = scraper(news_callable=lambda *args: pd.DataFrame())
    with pytest.raises(SourceContractError, match=source.source_id):
        await source.fetch(datetime(2020, 1, 1, tzinfo=UTC))


@pytest.mark.parametrize(
    "scraper",
    [
        EastmoneyGlobalScraper,
        ThsGlobalScraper,
        FutuGlobalScraper,
        SinaGlobalScraper,
        CjzcEmScraper,
        CctvNewsScraper,
    ],
)
async def test_upstream_exception_propagates(scraper):
    def broken(*args):
        raise RuntimeError("provider failed")

    with pytest.raises(RuntimeError, match="provider failed"):
        await scraper(news_callable=broken).fetch(datetime(2020, 1, 1, tzinfo=UTC))
