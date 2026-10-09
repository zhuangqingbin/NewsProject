"""Collect read-only A7 evidence; independent live comparison is still required."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from collections.abc import Awaitable, Sized
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Any

from quote_watcher.feeds.market_scan import MarketScanFeed
from quote_watcher.feeds.sector import SectorFeed
from quote_watcher.feeds.tencent import TencentFeed
from quote_watcher.storage.models import QuoteBarDaily
from quote_watcher.store.kline import DailyBar, DailyKlineCache, volume_averages
from shared.common.calendar import BJ, MarketCalendar
from shared.observability.log import configure_logging

REPRESENTATIVE_TICKERS = [("SH", "600519"), ("SZ", "300750"), ("SH", "688525")]


async def _probe[T: Sized](request: Awaitable[T]) -> tuple[T | None, dict[str, Any]]:
    try:
        async with asyncio.timeout(45):
            result = await request
        return result, {"status": "ok" if len(result) else "empty", "count": len(result)}
    except Exception as exc:
        # Do not include request URLs, response bodies or credentials in portable evidence.
        return None, {"status": "error", "error": type(exc).__name__}


def _read_history(db_path: Path, as_of: date) -> dict[str, list[DailyBar]]:
    """Read the existing database, including its WAL; never create it or warm its cache."""
    with closing(
        sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=2)
    ) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.row_factory = sqlite3.Row
        columns = {r[1] for r in conn.execute("PRAGMA table_info(quote_bars_daily)")}
        shares_column = "volume_shares" if "volume_shares" in columns else "NULL AS volume_shares"
        out = {}
        for _, ticker in REPRESENTATIVE_TICKERS:
            rows = conn.execute(
                "SELECT trade_date, open, high, low, close, prev_close, volume, amount, "
                f"{shares_column} "
                "FROM quote_bars_daily WHERE ticker = ? AND trade_date < ? "
                "ORDER BY trade_date DESC LIMIT 20",
                (ticker, as_of.isoformat()),
            ).fetchall()
            bars = []
            for row in reversed(rows):
                values = dict(row)
                values["trade_date"] = date.fromisoformat(values["trade_date"])
                bars.append(DailyKlineCache.row_to_bar(ticker, QuoteBarDaily(**values)))
            out[ticker] = bars
        return out


async def collect(db_path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Probe once. A ready report is evidence for a human comparison, never acceptance."""
    if now is not None and now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    market_feed, sector_feed = MarketScanFeed(), SectorFeed()
    (snapshots, quotes), (_, market), (_, sector) = await asyncio.gather(
        _probe(TencentFeed(max_retries=0).fetch(REPRESENTATIVE_TICKERS)),
        _probe(market_feed.fetch()),
        _probe(sector_feed.fetch_pct_changes()),
    )
    captured = (now or datetime.now(BJ)).astimezone(BJ)
    calendar = MarketCalendar()
    issues: list[str] = []
    if not calendar.is_open(captured):
        issues.append("market_closed")
    feeds = {"quotes": quotes, "market": market, "sector": sector}
    quotes["source"] = "tencent_hq"
    for name, feed in (("market", market_feed), ("sector", sector_feed)):
        feeds[name].update(
            source=feed.source_id, source_label=feed.source_label, upstream_total=feed.total
        )
    issues.extend(
        f"feed_unavailable:{name}" for name, result in feeds.items() if result["status"] != "ok"
    )
    history: dict[str, list[DailyBar]] = {}
    cache_error = None
    try:
        history = _read_history(db_path, captured.date())
    except (sqlite3.Error, ValueError, TypeError) as exc:
        cache_error = type(exc).__name__
        issues.append("daily_cache_unavailable")

    previous_day = calendar.previous_trading_day(captured.date())
    by_ticker = {(s.market, s.ticker): s for s in snapshots or []}
    evidence = []
    for market_id, ticker in REPRESENTATIVE_TICKERS:
        snap = by_ticker.get((market_id, ticker))
        if snap is None:
            issues.append(f"missing_quote:{ticker}")
            continue
        age = (captured - snap.ts).total_seconds()
        if not -5 <= age <= 90:
            issues.append(f"quote_timestamp:{ticker}")
        if snap.volume_ratio is None:
            issues.append(f"missing_volume_ratio:{ticker}")
        bars = history.get(ticker, [])
        if len(bars) < 20:
            issues.append(f"insufficient_history:{ticker}")
        if not bars or bars[-1].trade_date != previous_day:
            issues.append(f"stale_history:{ticker}")
        avg5, avg20 = volume_averages(bars)
        evidence.append(
            {
                "ticker": ticker,
                "market": market_id,
                "quote_ts": snap.ts.isoformat(),
                "quote_age_sec": age,
                "price": snap.price,
                "volume_shares": snap.volume,
                "volume_ratio": snap.volume_ratio,
                "completed_bar_count": len(bars),
                "latest_completed_bar": bars[-1].trade_date.isoformat() if bars else None,
                "volume_avg5d_shares": avg5 if len(bars) >= 5 else None,
                "volume_avg20d_shares": avg20 if len(bars) >= 20 else None,
            }
        )
    return {
        "schema_version": 1,
        "captured_at": captured.isoformat(),
        "session": calendar.session(captured),
        "expected_latest_completed_bar": previous_day.isoformat(),
        "eligible_for_manual_comparison": not issues,
        "acceptance_status": "pending_manual_comparison",
        "issues": issues,
        "feeds": feeds,
        "daily_cache_error": cache_error,
        "quotes": evidence,
        "required_manual_checks": [
            "Compare all three stock volumes, 5/20-day averages and source volume ratios "
            "with an independent live quote application at the recorded timestamp.",
            "Market and sector endpoints expose no timestamps: independently verify "
            "their freshness and ranking; a nonempty response alone is insufficient.",
            "Confirm quote_feed_ok logs and the first real alert; do not send a synthetic alert.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/quotes.db"))
    args = parser.parse_args(argv)
    # Keep stdout a single JSON document, including when existing feed clients log failures.
    configure_logging(level="CRITICAL")
    report = asyncio.run(collect(args.db))
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["eligible_for_manual_comparison"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
