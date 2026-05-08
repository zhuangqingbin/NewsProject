import pytest

from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase


@pytest.fixture
async def db() -> QuoteDatabase:
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    return db


@pytest.mark.asyncio
async def test_first_trigger_not_in_cooldown(db: QuoteDatabase):
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    assert await tracker.is_in_cooldown("rule_a", "600519", cooldown_min=30) is False


@pytest.mark.asyncio
async def test_after_mark_triggered_in_cooldown(db: QuoteDatabase):
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    await tracker.mark_triggered("rule_a", "600519", value=1.0)
    assert await tracker.is_in_cooldown("rule_a", "600519", cooldown_min=30) is True


@pytest.mark.asyncio
async def test_cooldown_expires(db: QuoteDatabase):
    times = iter([1000, 3000])  # mark @ 1000, check @ 3000 (33 min later)
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: next(times))
    await tracker.mark_triggered("rule_a", "600519", value=1.0)
    assert await tracker.is_in_cooldown("rule_a", "600519", cooldown_min=30) is False


@pytest.mark.asyncio
async def test_bump_count_increments(db: QuoteDatabase):
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    await tracker.mark_triggered("rule_a", "600519", value=1.0)
    await tracker.bump_count("rule_a", "600519")
    state = await tracker._dao.get("rule_a", "600519")
    assert state.trigger_count_today == 2


@pytest.mark.asyncio
async def test_mark_triggered_updates_existing(db: QuoteDatabase):
    times = iter([1000, 2000])
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: next(times))
    await tracker.mark_triggered("rule_a", "600519", value=1.0)
    await tracker.mark_triggered("rule_a", "600519", value=2.0)
    state = await tracker._dao.get("rule_a", "600519")
    assert state.last_triggered_at == 2000
    assert state.last_value == 2.0
    assert state.trigger_count_today == 2
