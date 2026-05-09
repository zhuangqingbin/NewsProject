"""Smoke test for preview_rules CLI argparse — actual replay tested manually."""
from __future__ import annotations

from datetime import date

from quote_watcher.tools.preview_rules import _parse_date, main


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
