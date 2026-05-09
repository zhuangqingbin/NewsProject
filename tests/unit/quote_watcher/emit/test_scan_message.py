from datetime import datetime
from zoneinfo import ZoneInfo

from quote_watcher.alerts.scan_ranker import ScanResult
from quote_watcher.emit.scan_message import build_market_scan_message
from quote_watcher.feeds.market_scan import MarketRow

BJ = ZoneInfo("Asia/Shanghai")


def _row(ticker: str, name: str, pct: float, vr: float | None = 1.0) -> MarketRow:
    return MarketRow(
        ticker=ticker, name=name, market="SH",
        price=10.0, pct_change=pct, volume=1000, amount=1.0,
        volume_ratio=vr,
    )


def test_full_scan_message():
    result = ScanResult(
        top_gainers=[_row("688256", "寒武纪", 9.2, 5.2), _row("688981", "中芯国际", 8.5, 4.0)],
        top_losers=[_row("600519", "贵州茅台", -3.2, 2.1)],
        top_volume_ratio=[_row("688256", "寒武纪", 9.2, 5.2), _row("002594", "比亚迪", 0.5, 3.8)],
    )
    now = datetime(2026, 5, 8, 14, 30, tzinfo=BJ)
    msg = build_market_scan_message(result, now=now)
    assert msg.kind == "market_scan"
    assert "14:30" in msg.title or "14:30" in msg.summary
    assert "异动榜" in msg.title
    # gainers
    assert "寒武纪" in msg.summary
    assert "9.2" in msg.summary  # +9.20% or +9.2%
    # losers
    assert "贵州茅台" in msg.summary
    assert "3.2" in msg.summary  # -3.20% or -3.2%
    # volume ratio
    assert "量比" in msg.summary
    assert "5.2" in msg.summary
    # badge
    assert any(b.text == "market_scan" for b in msg.badges)


def test_only_gainers():
    result = ScanResult(
        top_gainers=[_row("688256", "寒武纪", 9.2)],
        top_losers=[],
        top_volume_ratio=[],
    )
    msg = build_market_scan_message(result, now=datetime(2026, 5, 8, 10, 0, tzinfo=BJ))
    assert "寒武纪" in msg.summary
    assert "跌幅" not in msg.summary
    assert "量比异动" not in msg.summary


def test_empty_result_still_builds_message():
    result = ScanResult(top_gainers=[], top_losers=[], top_volume_ratio=[])
    msg = build_market_scan_message(result, now=datetime(2026, 5, 8, 10, 0, tzinfo=BJ))
    assert msg.kind == "market_scan"
    # Reasonable to expect a "no anomalies" placeholder; don't strictly assert
