import dataclasses

from news_pipeline.common.enums import Market
from news_pipeline.rules.patterns import Match, Pattern, PatternKind


def test_pattern_kind_values():
    assert PatternKind.TICKER.value == "ticker"
    assert PatternKind.ALIAS.value == "alias"
    assert PatternKind.SECTOR.value == "sector"
    assert PatternKind.MACRO.value == "macro"
    assert PatternKind.GENERIC.value == "generic"


def test_pattern_minimal():
    p = Pattern(
        text="nvda",
        is_english=True,
        kind=PatternKind.TICKER,
        market=Market.US,
        owner="NVDA",
    )
    assert p.text == "nvda"
    assert p.is_english is True


def test_pattern_chinese():
    p = Pattern(
        text="茅台",
        is_english=False,
        kind=PatternKind.ALIAS,
        market=Market.CN,
        owner="600519",
    )
    assert p.is_english is False


def test_pattern_frozen():
    p = Pattern(text="x", is_english=True, kind=PatternKind.TICKER, market=Market.US, owner="X")
    try:
        p.text = "y"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Pattern must be frozen")


def test_match():
    p = Pattern(
        text="nvda", is_english=True, kind=PatternKind.TICKER, market=Market.US, owner="NVDA"
    )
    m = Match(pattern=p, start=0, end=3, matched_text="nvda")
    assert m.start == 0 and m.end == 3
    assert m.matched_text == "nvda"
