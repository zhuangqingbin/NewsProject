from news_pipeline.config.schema import MarketScansCfg
from quote_watcher.alerts.scan_ranker import rank_market
from quote_watcher.feeds.market_scan import MarketRow


def _row(ticker: str, pct: float, vr: float | None = 1.0) -> MarketRow:
    return MarketRow(
        ticker=ticker, name=ticker, market="SH",
        price=10.0, pct_change=pct, volume=1000, amount=1.0,
        volume_ratio=vr,
    )


def test_rank_basic_top_n():
    rows = [
        _row("A", 9.0, 5.0),
        _row("B", 7.5, 0.8),
        _row("C", -8.0, 1.2),
        _row("D", -5.0, 4.0),
        _row("E", 0.5, 6.0),
    ]
    cfg = MarketScansCfg(push_top_n=2, only_when_score_above=0.0)
    result = rank_market(rows, cfg)
    assert [r.ticker for r in result.top_gainers] == ["A", "B"]
    assert [r.ticker for r in result.top_losers] == ["C", "D"]
    assert [r.ticker for r in result.top_volume_ratio] == ["E", "A"]


def test_score_above_filters_movers():
    rows = [
        _row("A", 9.0, 5.0),
        _row("B", 1.0, 5.0),  # below score threshold
        _row("C", -1.0, 5.0),
    ]
    cfg = MarketScansCfg(push_top_n=5, only_when_score_above=8.0)
    result = rank_market(rows, cfg)
    # Movers gated on |pct_change| > 8
    assert [r.ticker for r in result.top_gainers] == ["A"]
    assert result.top_losers == []
    # Volume ratio not gated by score threshold (it's a magnitude on its own scale)
    # But ranker should still apply only_when_score_above to volume_ratio too — vr ≥ threshold
    # All three have vr=5.0 < 8.0 → empty
    assert result.top_volume_ratio == []


def test_score_above_filters_volume_ratio_separately():
    rows = [
        _row("HOT", 0.5, 9.0),   # below pct threshold but big vol_ratio
        _row("COLD", 0.5, 1.0),
    ]
    cfg = MarketScansCfg(push_top_n=5, only_when_score_above=8.0)
    result = rank_market(rows, cfg)
    assert result.top_gainers == []
    assert result.top_losers == []
    assert [r.ticker for r in result.top_volume_ratio] == ["HOT"]


def test_rank_handles_none_volume_ratio():
    rows = [
        _row("A", 9.0, None),
        _row("B", -8.0, 5.0),
    ]
    cfg = MarketScansCfg(push_top_n=5, only_when_score_above=0.0)
    result = rank_market(rows, cfg)
    # None vol_ratio → excluded from volume ranking
    assert [r.ticker for r in result.top_volume_ratio] == ["B"]


def test_rank_empty_input():
    cfg = MarketScansCfg()
    result = rank_market([], cfg)
    assert result.top_gainers == []
    assert result.top_losers == []
    assert result.top_volume_ratio == []
