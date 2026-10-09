"""Tests for AlertEngine INDICATOR kind branch with DailyKlineCache injection."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.dao.quote_bars import QuoteBarsDailyDAO
from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.store.kline import DailyBar, DailyKlineCache

BJ = ZoneInfo("Asia/Shanghai")


@pytest.fixture
async def tracker(quote_db: QuoteDatabase) -> StateTracker:
    return StateTracker(dao=AlertStateDAO(quote_db), now_fn=lambda: 1000)


def _bar(d: date, close: float) -> DailyBar:
    return DailyBar(
        ticker="600519",
        trade_date=d,
        open=close,
        high=close,
        low=close,
        close=close,
        prev_close=close,
        volume=1000,
        amount=10000.0,
    )


def _snap(price: float) -> QuoteSnapshot:
    return QuoteSnapshot(
        ticker="600519",
        market="SH",
        name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=price,
        open=price,
        high=price,
        low=price,
        prev_close=price,
        volume=100,
        amount=1.0,
        bid1=price,
        ask1=price,
    )


@pytest.mark.asyncio
async def test_indicator_skipped_when_no_kline_cache(tracker: StateTracker):
    rule = AlertRule(
        id="r1",
        kind=AlertKind.INDICATOR,
        ticker="600519",
        expr="ma5 > 0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)  # no kline_cache
    snap = _snap(110.0)
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert verdicts == []  # silently skipped


@pytest.mark.asyncio
async def test_indicator_triggers_with_cross_above(tracker: StateTracker):
    """ma5 crosses above ma20 → fire."""
    bars = [
        _bar(
            date(2026, 1, 1) + __import__("datetime").timedelta(days=i),
            100.0 + (i * 0.1 if i < 18 else 5.0),
        )
        for i in range(25)
    ]
    # Construct so ma5 crosses ma20 at i=24: rising sharply at the end
    cache = AsyncMock()
    cache.get_cached.return_value = bars
    rule = AlertRule(
        id="r1",
        kind=AlertKind.INDICATOR,
        ticker="600519",
        expr="ma5 > ma20",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, kline_cache=cache)
    snap = _snap(120.0)
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert len(verdicts) == 1
    cache.get_cached.assert_awaited_once_with("600519", days=250)


@pytest.mark.asyncio
async def test_indicator_no_trigger_when_expr_false(tracker: StateTracker):
    bars = [
        _bar(date(2026, 1, 1) + __import__("datetime").timedelta(days=i), 100.0) for i in range(25)
    ]
    cache = AsyncMock()
    cache.get_cached.return_value = bars
    rule = AlertRule(
        id="r1",
        kind=AlertKind.INDICATOR,
        ticker="600519",
        expr="ma5 < ma20",  # flat → equal, not less
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, kline_cache=cache)
    snap = _snap(100.0)
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert verdicts == []


@pytest.mark.asyncio
async def test_indicator_target_filter(tracker: StateTracker):
    cache = AsyncMock()
    rule = AlertRule(
        id="r1",
        kind=AlertKind.INDICATOR,
        ticker="000001",
        expr="ma5 > 0",  # different ticker
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, kline_cache=cache)
    snap = _snap(100.0)
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert verdicts == []
    cache.get_cached.assert_not_called()


@pytest.mark.asyncio
async def test_threshold_still_works_with_kline_cache(tracker: StateTracker):
    """Regression: threshold rules unaffected by adding kline_cache."""
    cache = AsyncMock()
    rule = AlertRule(
        id="r1",
        kind=AlertKind.THRESHOLD,
        ticker="600519",
        expr="pct_change_intraday > 0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, kline_cache=cache)
    snap = QuoteSnapshot(
        ticker="600519",
        market="SH",
        name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=110.0,
        open=100,
        high=110,
        low=100,
        prev_close=100.0,
        volume=100,
        amount=1.0,
        bid1=110,
        ask1=110.01,
    )
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert len(verdicts) == 1


@pytest.mark.parametrize("kind", [AlertKind.THRESHOLD, AlertKind.INDICATOR])
async def test_rule_averages_use_cached_shares_and_exclude_today(quote_db, tracker, kind):
    dao = QuoteBarsDailyDAO(quote_db)
    rows = [
        (date(2026, 5, 7) - timedelta(days=19 - i), 100, 101, 99, 100, 100, (i + 1) * 100, 1e6)
        for i in range(20)
    ]
    rows += [(date(2026, 5, 8), 500, 501, 499, 500, 100, 999_999, 1e8)]
    await dao.upsert_many("600519", rows)
    rule = AlertRule(
        id="volumes",
        kind=kind,
        ticker="600519",
        expr="volume_avg5d == 180000 and volume_avg20d == 105000 and volume_ratio == 1.25",
    )
    snap = replace(_snap(100), volume=100_000, volume_ratio=1.25)
    engine = AlertEngine(rules=[rule], tracker=tracker, kline_cache=DailyKlineCache(quote_db))
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert len(verdicts) == 1
    assert verdicts[0].ctx_dump["volume_today"] == 100_000
    if kind == AlertKind.INDICATOR:
        assert verdicts[0].ctx_dump["ma5"] == 100  # today's cached close is not a prior close


async def test_explicit_average_override_is_preserved(tracker):
    cache = AsyncMock()
    cache.get_cached.return_value = [_bar(date(2026, 5, i), 100) for i in range(1, 8)]
    rule = AlertRule(
        id="override",
        kind=AlertKind.THRESHOLD,
        ticker="600519",
        expr="volume_avg5d == 50 and volume_avg20d == 0 and volume_ratio == 2",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, kline_cache=cache)
    assert (
        len(await engine.evaluate_for_snapshot(_snap(100), volume_avg5d=50, volume_avg20d=0)) == 1
    )


@pytest.mark.parametrize("trusted", ["none", "source", "override"])
async def test_stale_history_does_not_create_volume_ratio_alerts(tracker, trusted):
    cache = AsyncMock()
    cache.get_cached.return_value = [
        replace(_bar(date(2026, 1, 1) + timedelta(days=i), 100), volume=100_000) for i in range(20)
    ]
    rule = AlertRule(
        id="stale_volume", kind=AlertKind.THRESHOLD, ticker="600519", expr="volume_ratio >= 2"
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, kline_cache=cache)
    snap = replace(_snap(100), volume=300_000, volume_ratio=3 if trusted == "source" else None)
    kwargs = {"volume_avg5d": 100_000} if trusted == "override" else {}
    verdicts = await engine.evaluate_for_snapshot(snap, **kwargs)
    assert len(verdicts) == (0 if trusted == "none" else 1)
    if verdicts and trusted == "source":
        assert verdicts[0].ctx_dump["volume_avg5d"] == 0
