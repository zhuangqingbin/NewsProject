from news_pipeline.rules.verdict import RulesVerdict


def test_default_no_match():
    v = RulesVerdict(matched=False)
    assert v.matched is False
    assert v.tickers == []
    assert v.related_tickers == []
    assert v.sectors == []
    assert v.macros == []
    assert v.generic_hits == []
    assert v.markets == []
    assert v.score_boost == 0.0


def test_full_verdict():
    v = RulesVerdict(
        matched=True,
        tickers=["NVDA"],
        related_tickers=["AMD"],
        sectors=["semiconductor"],
        macros=["FOMC"],
        generic_hits=["powell"],
        markets=["us"],
        score_boost=85.0,
    )
    assert v.matched is True
    assert v.tickers == ["NVDA"]
    assert v.score_boost == 85.0


def test_frozen():
    import dataclasses

    v = RulesVerdict(matched=False)
    try:
        v.matched = True  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("RulesVerdict must be frozen")
