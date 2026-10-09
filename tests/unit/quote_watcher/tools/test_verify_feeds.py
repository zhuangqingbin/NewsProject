"""A7 evidence must not treat cached holiday quotes as live acceptance."""

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.feeds.market_scan import MarketScanFeed
from quote_watcher.feeds.sector import SectorFeed
from quote_watcher.feeds.tencent import TencentFeed
from quote_watcher.tools.verify_feeds import collect, main

BJ = ZoneInfo("Asia/Shanghai")
OPEN = datetime(2026, 10, 8, 10, 0, tzinfo=BJ)
TICKERS = [("SH", "600519"), ("SZ", "300750"), ("SH", "688525")]


@pytest.fixture
def daily_db(tmp_path):
    path = tmp_path / "quotes.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE quote_bars_daily (ticker TEXT, trade_date TEXT, open REAL, "
            "high REAL, low REAL, close REAL, prev_close REAL, volume INTEGER, amount REAL)"
        )
        days = [date(2026, 9, 30) - timedelta(days=n) for n in range(40)]
        days = sorted(d for d in days if d.weekday() < 5)[-20:]
        for _, ticker in TICKERS:
            for i, day in enumerate(days, 1):
                conn.execute(
                    "INSERT INTO quote_bars_daily VALUES (?, ?, 100, 102, 99, 101, 100, ?, 1e6)",
                    (ticker, day.isoformat(), i * 100),
                )
            for day in (date(2026, 10, 8), date(2026, 10, 9)):
                conn.execute(
                    "INSERT INTO quote_bars_daily VALUES (?, ?, 100, 102, 99, 101, 100, ?, 1e6)",
                    (ticker, day.isoformat(), 999_999),
                )
    return path


@pytest.fixture
def feeds(monkeypatch):
    snapshots = [
        QuoteSnapshot(
            ticker=code,
            market=market,
            name=code,
            ts=OPEN - timedelta(seconds=10),
            price=101,
            open=100,
            high=102,
            low=99,
            prev_close=100,
            volume=100_000,
            amount=1e7,
            bid1=101,
            ask1=101,
            volume_ratio=1.25,
        )
        for market, code in TICKERS
    ]
    quote = AsyncMock(return_value=snapshots)
    market = AsyncMock(return_value=[object()])
    sector = AsyncMock(return_value={"半导体": object()})
    monkeypatch.setattr(TencentFeed, "fetch", quote)
    monkeypatch.setattr(MarketScanFeed, "fetch", market)
    monkeypatch.setattr(SectorFeed, "fetch_pct_changes", sector)
    return quote, market, sector


async def test_collect_normalizes_completed_history_without_changing_db(daily_db, feeds):
    before = hashlib.sha256(daily_db.read_bytes()).hexdigest()
    report = await collect(daily_db, now=OPEN)
    assert report["eligible_for_manual_comparison"] is True
    assert report["acceptance_status"] == "pending_manual_comparison"
    assert report["issues"] == []
    assert len(report["quotes"]) == 3
    for row in report["quotes"]:
        assert row["volume_shares"] == 100_000
        assert row["volume_avg5d_shares"] == 180_000
        assert row["volume_avg20d_shares"] == 105_000
        assert row["latest_completed_bar"] == "2026-09-30"
        assert row["volume_ratio"] == 1.25
    assert hashlib.sha256(daily_db.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("age", [91, -6])
async def test_stale_or_future_quote_blocks_live_evidence(daily_db, feeds, age):
    feeds[0].return_value = [
        replace(s, ts=OPEN - timedelta(seconds=age)) for s in feeds[0].return_value
    ]
    report = await collect(daily_db, now=OPEN)
    assert not report["eligible_for_manual_comparison"]
    assert "quote_timestamp:600519" in report["issues"]


async def test_read_only_collection_includes_committed_wal(daily_db, feeds):
    with sqlite3.connect(daily_db) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(
            "UPDATE quote_bars_daily SET volume = 300 "
            "WHERE ticker = '600519' AND trade_date = '2026-09-30'"
        )
        writer.commit()
        wal_path = daily_db.with_name(daily_db.name + "-wal")
        before = (daily_db.read_bytes(), wal_path.read_bytes())
        report = await collect(daily_db, now=OPEN)
        assert report["quotes"][0]["volume_avg5d_shares"] == 146_000
        assert (daily_db.read_bytes(), wal_path.read_bytes()) == before


async def test_holiday_never_qualifies_as_live_acceptance(daily_db, feeds):
    report = await collect(daily_db, now=datetime(2026, 10, 7, 10, tzinfo=BJ))
    assert report["session"] == "closed"
    assert not report["eligible_for_manual_comparison"]
    assert "market_closed" in report["issues"]


async def test_missing_quotes_and_failed_sources_are_visible(daily_db, feeds):
    feeds[0].return_value = feeds[0].return_value[:2]
    feeds[1].side_effect = RuntimeError("private details must not enter the report")
    feeds[2].return_value = {}
    report = await collect(daily_db, now=OPEN)
    assert not report["eligible_for_manual_comparison"]
    assert "missing_quote:688525" in report["issues"]
    assert report["feeds"]["market"] == {"status": "error", "error": "RuntimeError"}
    assert report["feeds"]["sector"]["status"] == "empty"
    assert "private details" not in json.dumps(report)


async def test_missing_database_is_not_created(tmp_path, feeds):
    path = tmp_path / "absent.db"
    report = await collect(path, now=OPEN)
    assert not report["eligible_for_manual_comparison"]
    assert "daily_cache_unavailable" in report["issues"]
    assert not path.exists()


async def test_stale_and_insufficient_history_block_evidence(daily_db, feeds):
    with sqlite3.connect(daily_db) as conn:
        conn.execute("DELETE FROM quote_bars_daily WHERE trade_date = '2026-09-30'")
    report = await collect(daily_db, now=OPEN)
    assert not report["eligible_for_manual_comparison"]
    assert "insufficient_history:600519" in report["issues"]
    assert "stale_history:600519" in report["issues"]


def test_cli_emits_json_and_nonzero_for_incomplete_evidence(monkeypatch, capsys):
    monkeypatch.setattr(
        "quote_watcher.tools.verify_feeds.collect",
        AsyncMock(
            return_value={"eligible_for_manual_comparison": False, "issues": ["market_closed"]}
        ),
    )
    assert main(["--db", "unused.db"]) == 2
    assert json.loads(capsys.readouterr().out)["issues"] == ["market_closed"]
