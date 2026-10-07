from news_pipeline.rules.engine import _compile
from news_pipeline.rules.patterns import PatternKind


def _section():
    from news_pipeline.config.schema import (
        RulesSection,
        TickerEntry,
    )

    return RulesSection(
        us=[
            TickerEntry(
                ticker="NVDA",
                name="NVIDIA",
                aliases=["英伟达"],
                people=["黄仁勋"],
                sectors=["semiconductor"],
            ),
        ],
        short_alias_allow=["茅台"],
        cn=[
            TickerEntry(
                ticker="600519",
                name="贵州茅台",
                aliases=["茅台"],
                sectors=["白酒"],
            ),
        ],
    )


def test_compile_emits_all_pattern_kinds():
    patterns = _compile(_section())
    kinds = {p.kind for p in patterns}
    assert kinds == {
        PatternKind.TICKER,
        PatternKind.ALIAS,
        PatternKind.PERSON,
    }


def test_compile_ticker_pattern():
    patterns = _compile(_section())
    nvda = [p for p in patterns if p.kind == PatternKind.TICKER and p.owner == "NVDA"]
    assert len(nvda) == 1
    assert nvda[0].text == "nvda"
    assert nvda[0].is_english is True


def test_compile_alias_lowercase():
    patterns = _compile(_section())
    aliases = [p for p in patterns if p.kind == PatternKind.ALIAS]
    texts = {p.text for p in aliases}
    assert "nvidia" in texts
    assert "英伟达" in texts
    assert "贵州茅台" in texts
    assert "茅台" in texts


def test_compile_chinese_pattern_marked_not_english():
    patterns = _compile(_section())
    p = next(p for p in patterns if p.text == "茅台")
    assert p.is_english is False


def test_compile_empty_section():
    from news_pipeline.config.schema import RulesSection

    patterns = _compile(RulesSection())
    assert patterns == []
