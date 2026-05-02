from collections.abc import Callable

import akshare as ak
import pandas as pd

from news_pipeline.common.enums import Market
from news_pipeline.scrapers.common.akshare_global import AkshareGlobalScraper


class ThsGlobalScraper(AkshareGlobalScraper):
    """同花顺财经直播 — broad CN wire, complements 财联社/东财."""

    source_id = "ths_global"
    market = Market.CN
    body_col = "内容"

    def __init__(
        self,
        *,
        news_callable: Callable[[], pd.DataFrame] = ak.stock_info_global_ths,
    ) -> None:
        super().__init__(news_callable=news_callable)
