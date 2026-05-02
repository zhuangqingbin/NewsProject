from collections.abc import Callable

import akshare as ak
import pandas as pd

from news_pipeline.common.enums import Market
from news_pipeline.scrapers.common.akshare_global import AkshareGlobalScraper


class CjzcEmScraper(AkshareGlobalScraper):
    """东财财经早餐 — once-daily morning recap."""

    source_id = "cjzc_em"
    market = Market.CN
    body_col = "摘要"

    def __init__(
        self,
        *,
        news_callable: Callable[[], pd.DataFrame] = ak.stock_info_cjzc_em,
    ) -> None:
        super().__init__(news_callable=news_callable)
