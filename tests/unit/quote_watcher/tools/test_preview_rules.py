"""Smoke test for preview_rules CLI argparse — actual replay tested manually."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from quote_watcher.alerts.context import build_indicator_context
from quote_watcher.storage.models import QuoteBarDaily
from quote_watcher.tools.preview_rules import _make_snap, _parse_date, _row_to_bar, main


def test_parse_date():
    assert _parse_date("2026-05-08") == date(2026, 5, 8)


def test_main_rejects_invalid_date_order(monkeypatch, capsys):
    rc = main(["--tickers", "600519", "--since", "2026-05-10", "--until", "2026-05-01"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "since" in err.lower()


def test_main_rejects_empty_tickers():
    rc = main(["--tickers", " , ,", "--since", "2026-05-01", "--until", "2026-05-08"])
    assert rc == 1


def test_preview_uses_shares_for_daily_bars_and_synthetic_snapshots():
    row = QuoteBarDaily(
        ticker="600519",
        trade_date=date(2026, 5, 8),
        open=100,
        high=102,
        low=99,
        close=101,
        prev_close=100,
        volume=12_345,
        amount=1e6,
    )
    bar = _row_to_bar("600519", row)
    snap = _make_snap("600519", bar)
    assert bar.volume == snap.volume == 1_234_500
    assert row.volume == 12_345


def test_preview_indicator_averages_use_normalized_history():
    row = QuoteBarDaily(
        ticker="600519",
        trade_date=date(2026, 5, 7),
        open=100,
        high=102,
        low=99,
        close=101,
        prev_close=100,
        volume=100,
        amount=1e6,
    )
    bar = _row_to_bar("600519", row)
    snap = _make_snap("600519", replace(bar, trade_date=date(2026, 5, 8)))
    ctx = build_indicator_context(snap, bars=[bar] * 20)
    assert ctx["volume_avg5d"] == ctx["volume_avg20d"] == 10_000
    assert ctx["volume_ratio"] == 1
