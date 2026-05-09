# tests/unit/quote_watcher/alerts/test_sector_engine.py
import pytest

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.feeds.sector import SectorSnapshot
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase


@pytest.fixture
async def tracker() -> StateTracker:
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    return StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)


@pytest.mark.asyncio
async def test_sector_event_triggers(tracker: StateTracker):
    rule = AlertRule(
        id="semi_surge", kind=AlertKind.EVENT,
        target_kind="sector", sector="半导体",
        expr="sector_pct_change >= 3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    sector_snaps = {
        "半导体": SectorSnapshot(name="半导体", pct_change=3.5),
        "新能源": SectorSnapshot(name="新能源", pct_change=1.0),
    }
    verdicts = await engine.evaluate_sector(sector_snaps)
    assert len(verdicts) == 1
    assert verdicts[0].rule.id == "semi_surge"


@pytest.mark.asyncio
async def test_sector_event_no_trigger(tracker: StateTracker):
    rule = AlertRule(
        id="r1", kind=AlertKind.EVENT,
        target_kind="sector", sector="半导体",
        expr="sector_pct_change >= 3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    sector_snaps = {"半导体": SectorSnapshot(name="半导体", pct_change=2.0)}
    verdicts = await engine.evaluate_sector(sector_snaps)
    assert verdicts == []


@pytest.mark.asyncio
async def test_sector_event_missing_snapshot(tracker: StateTracker):
    rule = AlertRule(
        id="r1", kind=AlertKind.EVENT,
        target_kind="sector", sector="半导体",
        expr="sector_pct_change >= 3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    # Sector data missing for 半导体
    verdicts = await engine.evaluate_sector({"白酒": SectorSnapshot(name="白酒", pct_change=5.0)})
    assert verdicts == []


@pytest.mark.asyncio
async def test_sector_event_cooldown(tracker: StateTracker):
    rule = AlertRule(
        id="r1", kind=AlertKind.EVENT,
        target_kind="sector", sector="半导体",
        expr="sector_pct_change >= 3.0",
        cooldown_min=60,
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = {"半导体": SectorSnapshot(name="半导体", pct_change=3.5)}
    v1 = await engine.evaluate_sector(snap)
    v2 = await engine.evaluate_sector(snap)
    assert len(v1) == 1
    assert v2 == []  # cooldown


@pytest.mark.asyncio
async def test_sector_event_skip_non_sector_rules(tracker: StateTracker):
    """Threshold/composite/indicator rules MUST NOT be evaluated by evaluate_sector."""
    rules = [
        AlertRule(id="thr", kind=AlertKind.THRESHOLD, ticker="600519",
                  expr="pct_change_intraday <= -3"),
        AlertRule(id="evt_t", kind=AlertKind.EVENT, target_kind="ticker",
                  ticker="600519", expr="is_limit_up"),
    ]
    engine = AlertEngine(rules=rules, tracker=tracker)
    snap = {"半导体": SectorSnapshot(name="半导体", pct_change=10.0)}
    verdicts = await engine.evaluate_sector(snap)
    assert verdicts == []  # neither rule is a sector event
