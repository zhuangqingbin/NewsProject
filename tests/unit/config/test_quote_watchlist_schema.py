import pytest
from pydantic import ValidationError

from news_pipeline.config.schema import (
    MarketScansCfg,
    QuoteTickerEntry,
    QuoteWatchlistFile,
)


def test_minimal_quote_watchlist():
    f = QuoteWatchlistFile(cn=[
        QuoteTickerEntry(ticker="600519", name="贵州茅台", market="SH"),
    ])
    assert f.cn[0].ticker == "600519"
    assert f.us == []
    assert f.market_scans == {}


def test_duplicate_ticker_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        QuoteWatchlistFile(cn=[
            QuoteTickerEntry(ticker="600519", name="X", market="SH"),
            QuoteTickerEntry(ticker="600519", name="Y", market="SH"),
        ])


def test_market_scans_defaults():
    cfg = MarketScansCfg()
    assert cfg.top_gainers_n == 50
    assert cfg.push_top_n == 5
    assert cfg.only_when_score_above == 8.0


def test_invalid_market_letter():
    with pytest.raises(ValidationError):
        QuoteTickerEntry(ticker="600519", name="X", market="ABC")
