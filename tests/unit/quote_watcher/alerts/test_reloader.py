# tests/unit/quote_watcher/alerts/test_reloader.py
from pathlib import Path

import pytest

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.reloader import AlertsReloader
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase


@pytest.mark.asyncio
async def test_reloader_swaps_engine_rules_on_file_change(tmp_path: Path):
    alerts_file = tmp_path / "alerts.yml"
    alerts_file.write_text(
        "alerts:\n"
        "  - id: r1\n"
        "    kind: threshold\n"
        "    ticker: '600519'\n"
        "    expr: 'pct_change_intraday <= -3.0'\n",
        encoding="utf-8",
    )

    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    rule_old = AlertRule(
        id="old", kind=AlertKind.THRESHOLD,
        ticker="000001", expr="pct_change_intraday <= -1.0",
    )
    engine = AlertEngine(rules=[rule_old], tracker=tracker)

    reloader = AlertsReloader(alerts_path=alerts_file, engine=engine)

    # Direct call to the reload method (skip watchdog event plumbing)
    reloaded = reloader.reload_now()
    assert reloaded is True
    assert {r.id for r in engine._rules} == {"r1"}


@pytest.mark.asyncio
async def test_reloader_handles_invalid_yaml(tmp_path: Path):
    alerts_file = tmp_path / "alerts.yml"
    alerts_file.write_text("alerts: [", encoding="utf-8")  # invalid

    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    rule_old = AlertRule(
        id="old", kind=AlertKind.THRESHOLD,
        ticker="600519", expr="pct_change_intraday <= -3.0",
    )
    engine = AlertEngine(rules=[rule_old], tracker=tracker)

    reloader = AlertsReloader(alerts_path=alerts_file, engine=engine)
    reloaded = reloader.reload_now()
    assert reloaded is False
    # Original rules untouched
    assert engine._rules[0].id == "old"


@pytest.mark.asyncio
async def test_reloader_handles_missing_file(tmp_path: Path):
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    engine = AlertEngine(rules=[], tracker=tracker)
    reloader = AlertsReloader(alerts_path=tmp_path / "nope.yml", engine=engine)
    assert reloader.reload_now() is False
