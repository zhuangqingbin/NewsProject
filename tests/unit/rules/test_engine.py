from datetime import UTC, datetime

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.config.schema import (
    RulesSection,
    TickerEntry,
)
from news_pipeline.rules.engine import RulesEngine
from news_pipeline.rules.matcher import AhoCorasickMatcher


def _section():
    return RulesSection(
        us=[
            TickerEntry(
                ticker="NVDA",
                name="NVIDIA",
                aliases=["英伟达"],
                sectors=["semiconductor"],
            )
        ],
        short_alias_allow=["茅台"],
        cn=[
            TickerEntry(
                ticker="600519",
                name="贵州茅台",
                aliases=["茅台"],
                sectors=["白酒"],
            )
        ],
    )


def _article(title: str, body: str = "", market: Market = Market.US) -> RawArticle:
    return RawArticle(
        source="x",
        market=market,
        fetched_at=datetime(2026, 4, 26, tzinfo=UTC),
        published_at=datetime(2026, 4, 26, tzinfo=UTC),
        url="https://x.com/1",
        url_hash="h1",
        title=title,
        body=body,
        title_simhash=0,
        raw_meta={},
    )


def test_no_match():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("Random news about politics"))
    assert v.matched is False


def test_direct_ticker_match():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("NVDA reports earnings"))
    assert v.matched is True
    assert v.tickers == ["NVDA"]
    assert v.markets == ["us"]
    assert v.score_boost >= 50.0


def test_alias_match():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("英伟达发布新一代GPU"))
    assert v.matched is True
    assert v.tickers == ["NVDA"]


def test_chinese_substring_alias():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("贵州茅台一季报营收增长"))
    assert v.tickers == ["600519"]
    assert v.markets == ["cn"]


def test_sector_does_not_associate_ticker():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("Semiconductor industry rebounds"))
    assert v.matched is True
    assert "semiconductor" in v.generic_hits
    assert v.related_tickers == []
    assert v.tickers == []


def test_macro_does_not_associate_ticker():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("FOMC decision keeps rates unchanged"))
    assert v.macros == ["fomc"]
    assert v.related_tickers == []


def test_generic_keyword_no_ticker():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("Powell speaks at the Fed today"))
    assert v.matched is True
    assert v.tickers == []
    assert v.related_tickers == []
    assert "powell" in v.generic_hits


def test_multi_market_match():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("FOMC加息影响A股茅台"))
    assert v.markets == ["cn"]
