# src/news_pipeline/scrapers/factory.py
from collections.abc import Mapping

from news_pipeline.config.schema import (
    SecretsFile,
    SourcesFile,
    WatchlistFile,
)
from news_pipeline.scrapers.cn.akshare_news import AkshareNewsScraper
from news_pipeline.scrapers.cn.caixin_telegram import CaixinTelegramScraper
from news_pipeline.scrapers.cn.cctv_news import CctvNewsScraper
from news_pipeline.scrapers.cn.cjzc_em import CjzcEmScraper
from news_pipeline.scrapers.cn.eastmoney_global import EastmoneyGlobalScraper
from news_pipeline.scrapers.cn.juchao import JuchaoScraper
from news_pipeline.scrapers.cn.kr36 import Kr36Scraper
from news_pipeline.scrapers.cn.sina_global import SinaGlobalScraper
from news_pipeline.scrapers.cn.ths import ThsScraper
from news_pipeline.scrapers.cn.ths_global import ThsGlobalScraper
from news_pipeline.scrapers.cn.tushare_news import TushareNewsScraper
from news_pipeline.scrapers.cn.xueqiu import XueqiuScraper
from news_pipeline.scrapers.registry import ScraperRegistry
from news_pipeline.scrapers.us.finnhub import FinnhubScraper
from news_pipeline.scrapers.us.futu_global import FutuGlobalScraper
from news_pipeline.scrapers.us.sec_edgar import SecEdgarScraper
from news_pipeline.scrapers.us.wallstreetcn import WallStreetCnScraper
from news_pipeline.scrapers.us.yfinance_news import YFinanceNewsScraper


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
    s = secrets.sources

    if "finnhub" in enabled:
        reg.register(
            FinnhubScraper(token=s["finnhub_token"], tickers=us_tickers, category="general")
        )
    if "sec_edgar" in enabled and sec_ciks:
        reg.register(SecEdgarScraper(ciks=[sec_ciks[t] for t in us_tickers if t in sec_ciks]))
    if "yfinance_news" in enabled:
        reg.register(YFinanceNewsScraper(tickers=us_tickers))
    if "caixin_telegram" in enabled:
        reg.register(CaixinTelegramScraper())
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
    if "kr36" in enabled:
        reg.register(Kr36Scraper())
    if "akshare_news" in enabled and cn_tickers:
        reg.register(AkshareNewsScraper(tickers=cn_tickers))
    if "juchao" in enabled and cn_tickers:
        reg.register(JuchaoScraper(tickers=cn_tickers))
    if "xueqiu" in enabled and cn_tickers:
        reg.register(XueqiuScraper(tickers=cn_tickers, cookie=s["xueqiu_cookie"]))
    if "ths" in enabled and cn_tickers:
        reg.register(ThsScraper(tickers=cn_tickers, cookie=s["ths_cookie"]))
    if "tushare_news" in enabled:
        reg.register(TushareNewsScraper(src="sina"))
    return reg
