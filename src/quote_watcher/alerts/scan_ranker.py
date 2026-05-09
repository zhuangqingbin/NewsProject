"""Rank market spot rows for digest message."""
from __future__ import annotations

from dataclasses import dataclass

from news_pipeline.config.schema import MarketScansCfg
from quote_watcher.feeds.market_scan import MarketRow


@dataclass(frozen=True)
class ScanResult:
    top_gainers: list[MarketRow]
    top_losers: list[MarketRow]
    top_volume_ratio: list[MarketRow]


def rank_market(rows: list[MarketRow], cfg: MarketScansCfg) -> ScanResult:
    threshold = cfg.only_when_score_above
    n = cfg.push_top_n

    gainers = sorted(
        (r for r in rows if r.pct_change > threshold),
        key=lambda r: r.pct_change,
        reverse=True,
    )[:n]

    losers = sorted(
        (r for r in rows if r.pct_change < -threshold),
        key=lambda r: r.pct_change,
    )[:n]

    vol_ranked = sorted(
        (r for r in rows if r.volume_ratio is not None and r.volume_ratio >= threshold),
        key=lambda r: r.volume_ratio or 0.0,
        reverse=True,
    )[:n]

    return ScanResult(
        top_gainers=gainers,
        top_losers=losers,
        top_volume_ratio=vol_ranked,
    )
