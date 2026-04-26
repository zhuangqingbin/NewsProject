from news_pipeline.common.enums import Market
from news_pipeline.rules.matcher import (
    AhoCorasickMatcher,
    MatcherProtocol,
    build_matcher,
)
from news_pipeline.rules.patterns import Pattern, PatternKind


def _en(text: str, owner: str = "X", kind: PatternKind = PatternKind.TICKER) -> Pattern:
    return Pattern(
        text=text.lower(), is_english=text.isascii(),
        kind=kind, market=Market.US, owner=owner,
    )


def _cn(text: str, owner: str = "X", kind: PatternKind = PatternKind.ALIAS) -> Pattern:
    return Pattern(
        text=text.lower(), is_english=text.isascii(),
        kind=kind, market=Market.CN, owner=owner,
    )


def test_aho_protocol_compliance():
    assert isinstance(AhoCorasickMatcher(), MatcherProtocol)


def test_basic_english_match():
    m = AhoCorasickMatcher()
    m.rebuild([_en("NVDA", owner="NVDA")])
    matches = m.find_all("NVDA reports earnings beat")
    assert len(matches) == 1
    assert matches[0].pattern.owner == "NVDA"
    assert matches[0].matched_text == "nvda"


def test_word_boundary_protects_against_substring():
    m = AhoCorasickMatcher()
    m.rebuild([_en("NVDA", owner="NVDA")])
    matches = m.find_all("ENVDAQ shares")
    assert matches == []


def test_word_boundary_allows_punctuation():
    m = AhoCorasickMatcher()
    m.rebuild([_en("NVDA", owner="NVDA")])
    assert len(m.find_all("NVDA, AMD")) == 1
    assert len(m.find_all("AMD NVDA.")) == 1
    assert len(m.find_all("(NVDA)")) == 1


def test_chinese_substring_match():
    m = AhoCorasickMatcher()
    m.rebuild([_cn("茅台", owner="600519")])
    matches = m.find_all("贵州茅台公布业绩")
    assert len(matches) == 1
    assert matches[0].pattern.owner == "600519"


def test_case_insensitive():
    m = AhoCorasickMatcher()
    m.rebuild([_en("NVDA", owner="NVDA")])
    assert len(m.find_all("nvda news")) == 1
    assert len(m.find_all("Nvda News")) == 1
    assert len(m.find_all("NVDA")) == 1


def test_multiple_patterns_same_text():
    m = AhoCorasickMatcher()
    m.rebuild([
        _en("AI", owner="AI", kind=PatternKind.GENERIC),
        _en("AI", owner="AI", kind=PatternKind.SECTOR),
    ])
    matches = m.find_all("AI is the future")
    assert len(matches) == 2
    kinds = {m.pattern.kind for m in matches}
    assert kinds == {PatternKind.GENERIC, PatternKind.SECTOR}


def test_empty_patterns():
    m = AhoCorasickMatcher()
    m.rebuild([])
    assert m.find_all("anything") == []


def test_rebuild_overwrites():
    m = AhoCorasickMatcher()
    m.rebuild([_en("NVDA")])
    m.rebuild([_en("AMD")])
    matches = m.find_all("NVDA AMD")
    assert len(matches) == 1
    assert matches[0].pattern.text == "amd"


def test_factory_aho_corasick():
    matcher = build_matcher("aho_corasick", {})
    assert isinstance(matcher, AhoCorasickMatcher)


def test_factory_unknown_raises():
    import pytest
    with pytest.raises(ValueError, match="unknown matcher"):
        build_matcher("xxx", {})
