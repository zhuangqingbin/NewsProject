from collections.abc import Callable

import akshare as ak
import pandas as pd

from news_pipeline.common.enums import Market
from news_pipeline.scrapers.common.akshare_global import AkshareGlobalScraper


class FutuGlobalScraper(AkshareGlobalScraper):
    """富途快讯 — covers US/HK/A markets; categorized as US since the
    user's existing US sources (finnhub/sec_edgar) are narrowly per-ticker
    and need a broad-wire complement."""

    source_id = "futu_global"
    market = Market.US
    body_col = "内容"

    def __init__(
        self,
        *,
        news_callable: Callable[[], pd.DataFrame] = ak.stock_info_global_futu,
    ) -> None:
        super().__init__(news_callable=news_callable)
