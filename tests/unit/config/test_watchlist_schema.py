import pytest
from pydantic import ValidationError

from news_pipeline.config.schema import RulesSection, TickerEntry, WatchlistFile


def test_default_passes():
    watchlist = WatchlistFile()
    assert watchlist.effective_us() == watchlist.effective_cn() == []


def test_duplicate_ticker_rejects():
    with pytest.raises(ValidationError, match="duplicate tickers"):
        WatchlistFile(
            rules=RulesSection(
                us=[
                    TickerEntry(ticker="NVDA", name="NVIDIA"),
                    TickerEntry(ticker="NVDA", name="NVIDIA Corp"),
                ]
            )
        )


def test_valid_full_config():
    watchlist = WatchlistFile(
        rules=RulesSection(
            us=[
                TickerEntry(
                    ticker="NVDA", name="NVIDIA", aliases=["英伟达"], sectors=["semiconductor"]
                )
            ]
        )
    )
    assert watchlist.effective_us() == ["NVDA"]
    assert watchlist.rules.us[0].sectors == ["semiconductor"]
