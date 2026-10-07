# src/news_pipeline/scrapers/factory.py
from collections.abc import Mapping

from news_pipeline.config.schema import (
    SecretsFile,
    SourcesFile,
    WatchlistFile,
)
from news_pipeline.scrapers.cn.cctv_news import CctvNewsScraper
from news_pipeline.scrapers.cn.cjzc_em import CjzcEmScraper
from news_pipeline.scrapers.cn.cls_telegraph import ClsTelegraphScraper
from news_pipeline.scrapers.cn.eastmoney_global import EastmoneyGlobalScraper
from news_pipeline.scrapers.cn.em_stock_news import EmStockNewsScraper
from news_pipeline.scrapers.cn.juchao import JuchaoScraper
from news_pipeline.scrapers.cn.sina_global import SinaGlobalScraper
from news_pipeline.scrapers.cn.ths_global import ThsGlobalScraper
from news_pipeline.scrapers.registry import ScraperRegistry
from news_pipeline.scrapers.us.finnhub import FinnhubScraper
from news_pipeline.scrapers.us.futu_global import FutuGlobalScraper
from news_pipeline.scrapers.us.sec_edgar import SecEdgarScraper
from news_pipeline.scrapers.us.wallstreetcn import WallStreetCnScraper


def build_registry(
    sources: SourcesFile,
    watchlist: WatchlistFile,
    secrets: SecretsFile,
    *,
    sec_ciks: Mapping[str, str] | None = None,
) -> ScraperRegistry:
    reg = ScraperRegistry()
    us_tickers = [w.ticker for w in watchlist.rules.us]
    cn_tickers = [w.ticker for w in watchlist.rules.cn]
    enabled = {k for k, v in sources.sources.items() if v.enabled}
    supported = {
        "finnhub",
        "sec_edgar",
        "cls_telegraph",
        "eastmoney_global",
        "ths_global",
        "sina_global",
        "cjzc_em",
        "cctv_news",
        "futu_global",
        "wallstreetcn",
        "em_stock_news",
        "juchao",
    }
    unsupported = enabled - supported
    if unsupported:
        raise ValueError(f"Unsupported enabled sources: {', '.join(sorted(unsupported))}")
    s = secrets.sources

    if "finnhub" in enabled:
        reg.register(
            FinnhubScraper(token=s["finnhub_token"], tickers=us_tickers, category="general")
        )
    if "sec_edgar" in enabled:
        reg.register(
            SecEdgarScraper(
                tickers=us_tickers,
                user_agent=sources.sources["sec_edgar"].options.get("user_agent", ""),
                sec_ciks=sec_ciks,
                company_names={entry.ticker: entry.name for entry in watchlist.rules.us},
            )
        )
    if "cls_telegraph" in enabled:
        reg.register(ClsTelegraphScraper())
    if "eastmoney_global" in enabled:
        reg.register(EastmoneyGlobalScraper())
    if "ths_global" in enabled:
        reg.register(ThsGlobalScraper())
    if "sina_global" in enabled:
        reg.register(SinaGlobalScraper())
    if "cjzc_em" in enabled:
        reg.register(CjzcEmScraper())
    if "cctv_news" in enabled:
        reg.register(CctvNewsScraper())
    if "futu_global" in enabled:
        reg.register(FutuGlobalScraper())
    if "wallstreetcn" in enabled:
        reg.register(WallStreetCnScraper())
    if "em_stock_news" in enabled and cn_tickers:
        reg.register(EmStockNewsScraper(tickers=cn_tickers))
    if "juchao" in enabled and cn_tickers:
        reg.register(JuchaoScraper(tickers=cn_tickers))
    return reg
