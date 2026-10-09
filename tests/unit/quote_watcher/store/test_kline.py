from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest
from freezegun import freeze_time

from quote_watcher.storage.dao.quote_bars import QuoteBarsDailyDAO
from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.store.kline import DailyKlineCache


@pytest.fixture(autouse=True)
def fixed_trading_date():
    with freeze_time("2026-05-09 02:00:00"):
        yield


def _ak_df(rows: list[tuple]) -> pd.DataFrame:
    """Build fake akshare stock_zh_a_hist DataFrame.

    Columns are Chinese: 日期 / 开盘 / 收盘 / 最高 / 最低 / 成交量 / 成交额 ... (subset).
    """
    return pd.DataFrame(
        [
            {"日期": d, "开盘": o, "收盘": c, "最高": h, "最低": low, "成交量": vol, "成交额": amt}
            for d, o, h, low, c, vol, amt in rows
        ]
    )


@pytest.mark.asyncio
async def test_load_for_calls_akshare_on_cold_cache(quote_db: QuoteDatabase):
    df = _ak_df(
        [
            (date(2026, 5, 6), 100.0, 102.0, 99.0, 101.0, 10000, 1.0e6),
            (date(2026, 5, 7), 101.0, 103.0, 100.0, 102.5, 12000, 1.2e6),
            (date(2026, 5, 8), 102.5, 104.0, 102.0, 103.5, 15000, 1.5e6),
        ]
    )
    cache = DailyKlineCache(quote_db)
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
    assert [bar.volume for bar in bars] == [1_000_000, 1_200_000, 1_500_000]


@pytest.mark.asyncio
async def test_load_for_uses_db_on_warm_cache(quote_db: QuoteDatabase):
    df = _ak_df(
        [
            (date(2026, 5, 6), 100.0, 102.0, 99.0, 101.0, 10000, 1.0e6),
            (date(2026, 5, 7), 101.0, 103.0, 100.0, 102.5, 12000, 1.2e6),
            (date(2026, 5, 8), 102.5, 104.0, 102.0, 103.5, 15000, 1.5e6),
        ]
    )
    cache = DailyKlineCache(quote_db)
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
    assert out["600519"][0].volume == 1_000_000
    assert (await cache.get_cached("600519"))[0].volume == 1_000_000
    # Existing cache rows retain AKShare lots; reading must never multiply storage twice.
    assert (await QuoteBarsDailyDAO(quote_db).list_recent("600519", 3))[0].volume == 10_000


@pytest.mark.asyncio
@pytest.mark.parametrize("ticker", ["600519", "300750", "688525"])
async def test_existing_daily_cache_lots_are_exposed_as_shares(quote_db, ticker):
    dao = QuoteBarsDailyDAO(quote_db)
    await dao.upsert_many(ticker, [(date(2026, 5, 8), 100, 102, 99, 101, 100, 12_345, 1e6)])
    with patch("quote_watcher.store.kline.ak.stock_zh_a_hist") as fetch:
        bars = await DailyKlineCache(quote_db).get_cached(ticker, days=1)
    fetch.assert_not_called()
    # Daily history is lots even for STAR, unlike Tencent's intraday STAR field.
    assert bars[0].volume == 1_234_500


@pytest.mark.asyncio
async def test_load_for_handles_akshare_error(quote_db: QuoteDatabase):
    cache = DailyKlineCache(quote_db)
    with patch(
        "quote_watcher.store.kline.ak.stock_zh_a_hist",
        side_effect=RuntimeError("net"),
    ):
        out = await cache.load_for(["600519"], days=3)
    # On error: return empty list rather than crash
    assert out == {"600519": []}


@pytest.mark.asyncio
async def test_get_cached_returns_db_only(quote_db: QuoteDatabase):
    df = _ak_df(
        [
            (date(2026, 5, 7), 100.0, 102.0, 99.0, 101.0, 10000, 1.0e6),
            (date(2026, 5, 8), 101.0, 103.0, 100.0, 102.5, 12000, 1.2e6),
        ]
    )
    cache = DailyKlineCache(quote_db)
    with patch(
        "quote_watcher.store.kline.ak.stock_zh_a_hist",
        return_value=df,
    ):
        await cache.load_for(["600519"], days=2)
    bars = await cache.get_cached("600519", days=2)
    assert len(bars) == 2


@pytest.mark.asyncio
async def test_load_for_multiple_tickers(quote_db: QuoteDatabase):
    df1 = _ak_df([(date(2026, 5, 8), 100, 102, 99, 101, 10000, 1e6)])
    df2 = _ak_df([(date(2026, 5, 8), 200, 205, 198, 203, 20000, 2e6)])

    def fake_ak(symbol, **kwargs):
        return df1 if symbol == "600519" else df2

    cache = DailyKlineCache(quote_db)
    with patch("quote_watcher.store.kline.ak.stock_zh_a_hist", side_effect=fake_ak):
        out = await cache.load_for(["600519", "300750"], days=1)
    assert out["600519"][0].close == 101
    assert out["300750"][0].close == 203


async def test_full_but_stale_cache_refreshes_on_next_trading_day(quote_db):
    dao = QuoteBarsDailyDAO(quote_db)
    await dao.upsert_many("600519", [(date(2026, 5, 6), 100, 102, 99, 101, 100, 100, 1e6)])
    df = _ak_df([(date(2026, 5, 8), 100, 102, 99, 101, 200, 2e6)])
    with patch("quote_watcher.store.kline.ak.stock_zh_a_hist", return_value=df) as fetch:
        bars = await DailyKlineCache(quote_db).load_for(["600519"], days=1)
    fetch.assert_called_once()
    assert bars["600519"][-1].trade_date == date(2026, 5, 8)
    assert bars["600519"][-1].volume == 20_000


async def test_intraday_history_is_not_saved_as_a_completed_bar(quote_db):
    cache = DailyKlineCache(quote_db)
    df = _ak_df(
        [
            (date(2026, 9, 30), 100, 102, 99, 101, 200, 2e6),
            (date(2026, 10, 8), 100, 102, 99, 101, 10, 1e5),
        ]
    )
    with (
        freeze_time("2026-10-08 02:00:00"),
        patch("quote_watcher.store.kline.ak.stock_zh_a_hist", return_value=df) as fetch,
    ):
        bars = await cache.load_for(["600519"], days=1)
    assert fetch.call_args.kwargs["start_date"] <= fetch.call_args.kwargs["end_date"]
    assert bars["600519"][-1].trade_date == date(2026, 9, 30)
    rows = await QuoteBarsDailyDAO(quote_db).list_recent("600519", 10)
    assert [r.trade_date for r in rows] == [date(2026, 9, 30)]
    df.loc[df["日期"] == date(2026, 10, 8), "成交量"] = 500
    with (
        freeze_time("2026-10-09 02:00:00"),
        patch("quote_watcher.store.kline.ak.stock_zh_a_hist", return_value=df) as fetch,
    ):
        bars = await cache.load_for(["600519"], days=1)
    fetch.assert_called_once()
    assert bars["600519"][-1].volume == 50_000


async def test_legacy_partial_bar_is_refetched_and_hidden_if_refresh_fails(quote_db):
    dao = QuoteBarsDailyDAO(quote_db)
    await dao.upsert_many("600519", [(date(2026, 5, 8), 100, 102, 99, 101, 100, 10, 1e5)])
    cache = DailyKlineCache(quote_db)
    with patch("quote_watcher.store.kline.ak.stock_zh_a_hist", side_effect=RuntimeError("net")):
        assert await cache.load_for(["600519"], days=1) == {"600519": []}
    assert await cache.get_cached("600519", days=1) == []
    df = _ak_df([(date(2026, 5, 8), 100, 102, 99, 101, 500, 2e6)])
    with patch("quote_watcher.store.kline.ak.stock_zh_a_hist", return_value=df) as fetch:
        bars = await cache.load_for(["600519"], days=1)
    fetch.assert_called_once()
    assert bars["600519"][-1].volume == 50_000
