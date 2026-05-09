"""Build market_scan digest CommonMessage from ScanResult."""
from __future__ import annotations

from datetime import datetime

from quote_watcher.alerts.scan_ranker import ScanResult
from quote_watcher.feeds.market_scan import MarketRow
from shared.common.contracts import Badge, CommonMessage
from shared.common.enums import Market


def _format_mover_lines(label_emoji: str, label: str, rows: list[MarketRow]) -> list[str]:
    if not rows:
        return []
    out = [f"{label_emoji} {label} top {len(rows)}:"]
    for i, r in enumerate(rows, 1):
        out.append(f"{i}. {r.name} ({r.ticker})  {r.pct_change:+.2f}%")
    return out


def _format_volume_lines(rows: list[MarketRow]) -> list[str]:
    if not rows:
        return []
    out = [f"📈 量比异动 top {len(rows)}:"]
    for r in rows:
        vr = r.volume_ratio if r.volume_ratio is not None else 0.0
        out.append(f"- {r.name} ({r.ticker}) 量比 {vr:.2f}")
    return out


def build_market_scan_message(
    result: ScanResult,
    *,
    now: datetime,
) -> CommonMessage:
    sections: list[str] = []
    g = _format_mover_lines("🚀", "涨幅", result.top_gainers)
    l_ = _format_mover_lines("📉", "跌幅", result.top_losers)
    v = _format_volume_lines(result.top_volume_ratio)
    if g:
        sections.append("\n".join(g))
    if l_:
        sections.append("\n".join(l_))
    if v:
        sections.append("\n".join(v))

    summary = "无异动" if not sections else "\n\n".join(sections)

    title = f"📊 A股 {now.strftime('%H:%M')} 异动榜"
    return CommonMessage(
        title=title,
        summary=summary,
        source_label="quote_watcher",
        source_url="https://quote.eastmoney.com/center.html",
        badges=[Badge(text="market_scan", color="blue")],
        chart_url=None,
        deeplinks=[],
        market=Market.CN,
        kind="market_scan",
    )
