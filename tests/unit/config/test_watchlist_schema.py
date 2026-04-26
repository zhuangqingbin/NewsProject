import pytest
from pydantic import ValidationError

from news_pipeline.config.schema import (
    LLMSection, MarketKeywords, RulesSection, TickerEntry, WatchlistFile,
)


def test_default_passes():
    w = WatchlistFile()
    assert w.rules.enable is True
    assert w.llm.enable is False


def test_both_disabled_rejects():
    with pytest.raises(ValidationError, match="both False"):
        WatchlistFile(
            rules=RulesSection(enable=False),
            llm=LLMSection(enable=False),
        )


def test_only_llm_enabled_passes():
    w = WatchlistFile(
        rules=RulesSection(enable=False),
        llm=LLMSection(enable=True),
    )
    assert w.rules.enable is False
    assert w.llm.enable is True


def test_duplicate_ticker_rejects():
    with pytest.raises(ValidationError, match="duplicate tickers"):
        WatchlistFile(rules=RulesSection(
            us=[
                TickerEntry(ticker="NVDA", name="NVIDIA"),
                TickerEntry(ticker="NVDA", name="NVIDIA Corp"),
            ],
        ))


def test_invalid_sector_ref_rejects():
    with pytest.raises(ValidationError, match="not in sector_keywords"):
        WatchlistFile(rules=RulesSection(
            us=[TickerEntry(
                ticker="NVDA", name="NVIDIA",
                sectors=["nonexistent_sector"],
            )],
            sector_keywords=MarketKeywords(us=["semiconductor"]),
        ))


def test_invalid_macro_link_rejects():
    with pytest.raises(ValidationError, match="not in macro_keywords"):
        WatchlistFile(rules=RulesSection(
            us=[TickerEntry(
                ticker="NVDA", name="NVIDIA",
                macro_links=["nonexistent_macro"],
            )],
            macro_keywords=MarketKeywords(us=["FOMC"]),
        ))


def test_valid_full_config():
    w = WatchlistFile(rules=RulesSection(
        us=[TickerEntry(
            ticker="NVDA", name="NVIDIA",
            aliases=["英伟达"],
            sectors=["semiconductor"],
            macro_links=["FOMC"],
        )],
        sector_keywords=MarketKeywords(us=["semiconductor"]),
        macro_keywords=MarketKeywords(us=["FOMC"]),
    ))
    assert len(w.rules.us) == 1
    assert w.rules.us[0].ticker == "NVDA"


def test_gray_zone_action_default():
    s = RulesSection()
    assert s.gray_zone_action == "digest"


def test_gray_zone_action_invalid_rejects():
    with pytest.raises(ValidationError):
        RulesSection(gray_zone_action="invalid_value")  # type: ignore[arg-type]


def test_matcher_default():
    s = RulesSection()
    assert s.matcher == "aho_corasick"
