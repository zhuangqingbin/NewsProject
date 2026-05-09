from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.store.kline import DailyKlineCache


def _ak_df(rows: list[tuple]) -> pd.DataFrame:
    """Build fake akshare stock_zh_a_hist DataFrame.

    Columns are Chinese: 日期 / 开盘 / 收盘 / 最高 / 最低 / 成交量 / 成交额 ... (subset).
    """
    return pd.DataFrame([
        {"日期": d, "开盘": o, "收盘": c, "最高": h, "最低": low,
         "成交量": vol, "成交额": amt}
        for d, o, h, low, c, vol, amt in rows
    ])


@pytest.fixture
async def db():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    return db


@pytest.mark.asyncio
async def test_load_for_calls_akshare_on_cold_cache(db):
    df = _ak_df([
        (date(2026, 5, 6), 100.0, 102.0, 99.0, 101.0, 10000, 1.0e6),
        (date(2026, 5, 7), 101.0, 103.0, 100.0, 102.5, 12000, 1.2e6),
        (date(2026, 5, 8), 102.5, 104.0, 102.0, 103.5, 15000, 1.5e6),
    ])
    cache = DailyKlineCache(db)
    with patch(
        "quote_watcher.store.kline.ak.stock_zh_a_hist",
        return_value=df,
    ) as mock_ak:
        out = await cache.load_for(["600519"], days=3)
    assert mock_ak.call_count == 1
    bars = out["600519"]
    assert len(bars) == 3
    assert bars[0].trade_date == date(2026, 5, 6)
    assert bars[2].close == 103.5
    # prev_close should be derived from previous row (row 0 has no prev — leave 0 or first close)
    assert bars[1].prev_close == 101.0
    assert bars[2].prev_close == 102.5


@pytest.mark.asyncio
async def test_load_for_uses_db_on_warm_cache(db):
    df = _ak_df([
        (date(2026, 5, 6), 100.0, 102.0, 99.0, 101.0, 10000, 1.0e6),
        (date(2026, 5, 7), 101.0, 103.0, 100.0, 102.5, 12000, 1.2e6),
        (date(2026, 5, 8), 102.5, 104.0, 102.0, 103.5, 15000, 1.5e6),
    ])
    cache = DailyKlineCache(db)
    # First call populates DB
    with patch(
        "quote_watcher.store.kline.ak.stock_zh_a_hist",
        return_value=df,
    ) as mock_ak:
        await cache.load_for(["600519"], days=3)
        assert mock_ak.call_count == 1
    # Second call should NOT hit akshare (cache hit)
    with patch(
        "quote_watcher.store.kline.ak.stock_zh_a_hist",
        return_value=df,
    ) as mock_ak2:
        out = await cache.load_for(["600519"], days=3)
        assert mock_ak2.call_count == 0
    assert len(out["600519"]) == 3


@pytest.mark.asyncio
async def test_load_for_handles_akshare_error(db):
    cache = DailyKlineCache(db)
    with patch(
        "quote_watcher.store.kline.ak.stock_zh_a_hist",
        side_effect=RuntimeError("net"),
    ):
        out = await cache.load_for(["600519"], days=3)
    # On error: return empty list rather than crash
    assert out == {"600519": []}


@pytest.mark.asyncio
async def test_get_cached_returns_db_only(db):
    df = _ak_df([
        (date(2026, 5, 6), 100.0, 102.0, 99.0, 101.0, 10000, 1.0e6),
        (date(2026, 5, 7), 101.0, 103.0, 100.0, 102.5, 12000, 1.2e6),
    ])
    cache = DailyKlineCache(db)
    with patch(
        "quote_watcher.store.kline.ak.stock_zh_a_hist", return_value=df,
    ):
        await cache.load_for(["600519"], days=2)
    bars = await cache.get_cached("600519", days=2)
    assert len(bars) == 2


@pytest.mark.asyncio
async def test_load_for_multiple_tickers(db):
    df1 = _ak_df([(date(2026, 5, 8), 100, 102, 99, 101, 10000, 1e6)])
    df2 = _ak_df([(date(2026, 5, 8), 200, 205, 198, 203, 20000, 2e6)])

    def fake_ak(symbol, **kwargs):
        return df1 if symbol == "600519" else df2

    cache = DailyKlineCache(db)
    with patch("quote_watcher.store.kline.ak.stock_zh_a_hist", side_effect=fake_ak):
        out = await cache.load_for(["600519", "300750"], days=1)
    assert out["600519"][0].close == 101
    assert out["300750"][0].close == 203
