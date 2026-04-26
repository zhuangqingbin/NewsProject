from news_pipeline.rules.engine import _compile
from news_pipeline.rules.patterns import PatternKind


def _section():
    from news_pipeline.config.schema import (
        MarketKeywords,
        RulesSection,
        TickerEntry,
    )

    return RulesSection(
        enable=True,
        us=[
            TickerEntry(
                ticker="NVDA",
                name="NVIDIA",
                aliases=["英伟达"],
                sectors=["semiconductor"],
                macro_links=["FOMC"],
            ),
        ],
        cn=[
            TickerEntry(
                ticker="600519",
                name="贵州茅台",
                aliases=["茅台"],
                sectors=["白酒"],
                macro_links=["央行"],
            ),
        ],
        keyword_list=MarketKeywords(us=["powell"], cn=["证监会"]),
        macro_keywords=MarketKeywords(us=["FOMC", "CPI"], cn=["央行"]),
        sector_keywords=MarketKeywords(us=["semiconductor"], cn=["白酒"]),
    )


def test_compile_emits_all_pattern_kinds():
    patterns, _sec_idx, _mac_idx = _compile(_section())
    kinds = {p.kind for p in patterns}
    assert kinds == {
        PatternKind.TICKER,
        PatternKind.ALIAS,
        PatternKind.SECTOR,
        PatternKind.MACRO,
        PatternKind.GENERIC,
    }


def test_compile_ticker_pattern():
    patterns, _, _ = _compile(_section())
    nvda = [p for p in patterns if p.kind == PatternKind.TICKER and p.owner == "NVDA"]
    assert len(nvda) == 1
    assert nvda[0].text == "nvda"
    assert nvda[0].is_english is True


def test_compile_alias_lowercase():
    patterns, _, _ = _compile(_section())
    aliases = [p for p in patterns if p.kind == PatternKind.ALIAS]
    texts = {p.text for p in aliases}
    assert "nvidia" in texts
    assert "英伟达" in texts
    assert "贵州茅台" in texts
    assert "茅台" in texts


def test_compile_sector_reverse_index():
    _, sec_idx, _ = _compile(_section())
    assert sec_idx["semiconductor"] == {"NVDA"}
    assert sec_idx["白酒"] == {"600519"}


def test_compile_macro_reverse_index():
    _, _, mac_idx = _compile(_section())
    assert mac_idx["fomc"] == {"NVDA"}
    assert mac_idx["央行"] == {"600519"}


def test_compile_chinese_pattern_marked_not_english():
    patterns, _, _ = _compile(_section())
    p = next(p for p in patterns if p.text == "茅台")
    assert p.is_english is False


def test_compile_empty_section():
    from news_pipeline.config.schema import RulesSection

    patterns, sec_idx, mac_idx = _compile(RulesSection(enable=True))
    assert patterns == []
    assert sec_idx == {}
    assert mac_idx == {}
