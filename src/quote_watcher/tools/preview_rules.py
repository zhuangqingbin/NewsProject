"""Historical rule preview — replay daily K against configured INDICATOR rules.

Usage:
    uv run python -m quote_watcher.tools.preview_rules \\
        --tickers 600519,300750 --since 2026-04-01 --until 2026-05-08
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import asteval

from news_pipeline.config.loader import ConfigLoader
from quote_watcher.alerts.context import build_indicator_context
from quote_watcher.alerts.rule import AlertKind
from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.storage.dao.quote_bars import QuoteBarsDailyDAO
from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.storage.models import QuoteBarDaily
from quote_watcher.store.kline import DailyBar

BJ = ZoneInfo("Asia/Shanghai")


def _row_to_bar(ticker: str, row: QuoteBarDaily) -> DailyBar:
    return DailyBar(
        ticker=ticker,
        trade_date=row.trade_date,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        prev_close=row.prev_close,
        volume=row.volume,
        amount=row.amount,
    )


def _make_snap(ticker: str, bar: DailyBar) -> QuoteSnapshot:
    """Synthetic snapshot using bar's close as 'today's price'."""
    return QuoteSnapshot(
        ticker=ticker,
        market="SH",
        name=ticker,
        ts=datetime.combine(bar.trade_date, datetime.min.time(), tzinfo=BJ),
        price=bar.close,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        prev_close=bar.prev_close,
        volume=bar.volume,
        amount=bar.amount,
        bid1=bar.close,
        ask1=bar.close,
    )


def _eval_expr(expr: str, ctx: dict[str, Any]) -> bool:
    interp = asteval.Interpreter(usersyms=ctx, no_print=True, no_assert=True)
    try:
        result = bool(interp(expr))
    except Exception:
        return False
    if interp.error:
        return False
    return result


async def preview(
    tickers: list[str],
    since: date,
    until: date,
    config_dir: Path,
    db_path: str,
) -> tuple[int, int]:
    """Returns (rule_days_evaluated, fires)."""
    loader = ConfigLoader(config_dir)
    cfg = loader.load()
    db = QuoteDatabase(f"sqlite+aiosqlite:///{db_path}")
    await db.initialize()
    dao = QuoteBarsDailyDAO(db)

    indicator_rules = [
        r for r in cfg.alerts.alerts
        if r.kind == AlertKind.INDICATOR
    ]
    if not indicator_rules:
        print("No INDICATOR rules configured. Add some to config/alerts.yml first.")
        await db.close()
        return 0, 0

    fires = 0
    rule_count = 0
    for ticker in tickers:
        # Load enough history (500 days before `since` to compute MA60/RSI/MACD)
        all_bars_rows = await dao.list_recent(ticker, days=500)
        all_bars = [_row_to_bar(ticker, r) for r in all_bars_rows]
        if not all_bars:
            print(
                f"[{ticker}] No daily K data found in DB. "
                "Run main.py first to warm cache."
            )
            continue

        ticker_rules = [r for r in indicator_rules if r.ticker == ticker]
        if not ticker_rules:
            print(f"[{ticker}] No INDICATOR rules for this ticker — skipping.")
            continue

        for i, bar in enumerate(all_bars):
            if not (since <= bar.trade_date <= until):
                continue
            bars_so_far = all_bars[:i]  # history only, exclude today's bar
            snap_today = _make_snap(ticker, bar)
            ctx = build_indicator_context(snap_today, bars=bars_so_far)
            for rule in ticker_rules:
                rule_count += 1
                if _eval_expr(rule.expr, ctx):
                    fires += 1
                    print(
                        f"[{bar.trade_date}] {ticker} {rule.id}: TRIGGERED"
                        f" (price={bar.close}, expr={rule.expr})"
                    )

    print(f"\nReplayed {rule_count} rule-days → {fires} fires (no pushes)")
    await db.close()
    return rule_count, fires


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview which INDICATOR rules would have fired in a date range"
    )
    parser.add_argument(
        "--tickers",
        required=True,
        help="Comma-separated list of tickers (e.g. 600519,300750)",
    )
    parser.add_argument("--since", required=True, type=_parse_date)
    parser.add_argument("--until", required=True, type=_parse_date)
    parser.add_argument("--config-dir", default="config", type=Path)
    parser.add_argument("--db", default="data/quotes.db")
    args = parser.parse_args(argv)

    if args.since > args.until:
        print("--since must be <= --until", file=sys.stderr)
        return 1

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        print("--tickers is empty", file=sys.stderr)
        return 1

    asyncio.run(
        preview(
            tickers=tickers,
            since=args.since,
            until=args.until,
            config_dir=args.config_dir,
            db_path=args.db,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
