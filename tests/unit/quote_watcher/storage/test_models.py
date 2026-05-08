import pytest
from sqlalchemy import select

from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.storage.models import (
    AlertHistory,
    AlertState,
    QuoteBar1min,
    QuoteBarDaily,
)


@pytest.mark.asyncio
async def test_create_alert_state_and_query():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()

    async with db.session() as sess:
        sess.add(AlertState(
            rule_id="rule_a", ticker="600519",
            last_triggered_at=12345, last_value=1.0, trigger_count_today=1,
        ))
        await sess.commit()

        result = await sess.execute(
            select(AlertState).where(AlertState.rule_id == "rule_a")
        )
        row = result.scalar_one()
        assert row.ticker == "600519"
        assert row.trigger_count_today == 1
    await db.close()


@pytest.mark.asyncio
async def test_alert_state_composite_pk():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()

    async with db.session() as sess:
        sess.add(AlertState(rule_id="r1", ticker="A", last_triggered_at=1))
        sess.add(AlertState(rule_id="r1", ticker="B", last_triggered_at=2))  # different ticker, OK
        sess.add(AlertState(rule_id="r2", ticker="A", last_triggered_at=3))  # different rule, OK
        await sess.commit()

        rows = (await sess.execute(select(AlertState))).scalars().all()
        assert len(rows) == 3
    await db.close()


@pytest.mark.asyncio
async def test_quote_bars_can_insert():
    from datetime import UTC, date, datetime

    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()

    async with db.session() as sess:
        sess.add(QuoteBar1min(
            ticker="600519",
            bar_start=datetime(2026, 5, 8, 10, 0, tzinfo=UTC),
            open=100, high=101, low=99, close=100.5,
            volume=1000, amount=100500.0,
        ))
        sess.add(QuoteBarDaily(
            ticker="600519", trade_date=date(2026, 5, 8),
            open=100, high=105, low=98, close=102, prev_close=100,
            volume=10000, amount=1020000.0,
        ))
        sess.add(AlertHistory(
            rule_id="r1", ticker="600519",
            triggered_at=datetime(2026, 5, 8, 10, 0, tzinfo=UTC),
            snapshot_json='{"price":102}', pushed=True,
        ))
        await sess.commit()
    await db.close()
