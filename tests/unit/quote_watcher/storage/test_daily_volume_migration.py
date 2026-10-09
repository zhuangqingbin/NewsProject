import sqlite3
from datetime import date

from quote_watcher.storage.dao.quote_bars import QuoteBarsDailyDAO
from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.store.kline import DailyKlineCache


async def test_initialize_adds_exact_shares_column_without_rewriting_legacy_lots(tmp_path):
    path = tmp_path / "old-quotes.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE quote_bars_daily (id INTEGER PRIMARY KEY, ticker VARCHAR(10), "
            "trade_date DATE, open FLOAT, high FLOAT, low FLOAT, close FLOAT, prev_close FLOAT, "
            "volume BIGINT, amount FLOAT, UNIQUE(ticker, trade_date))"
        )
        conn.execute(
            "INSERT INTO quote_bars_daily VALUES "
            "(1, '688525', '2026-10-08', 190, 193, 182, 183, 192, 164884, 3e9)"
        )
    db = QuoteDatabase(f"sqlite+aiosqlite:///{path}")
    try:
        await db.initialize()
        await db.initialize()
        rows = await QuoteBarsDailyDAO(db).list_recent("688525", 1)
        assert rows[0].volume == 164884
        assert rows[0].volume_shares is None
        assert DailyKlineCache.row_to_bar("688525", rows[0]).volume == 16_488_400
        dao = QuoteBarsDailyDAO(db)
        await dao.upsert_many(
            "688525",
            [(date(2026, 10, 8), 190, 193, 182, 183, 192, 164884, 3e9)],
            volume_shares={date(2026, 10, 8): 16_488_424},
        )
        assert (
            DailyKlineCache.row_to_bar("688525", (await dao.list_recent("688525", 1))[0]).volume
            == 16_488_424
        )
        # A subsequent Eastmoney refresh clears the obsolete Tencent override.
        await dao.upsert_many("688525", [(date(2026, 10, 8), 190, 193, 182, 183, 192, 170000, 3e9)])
        row = (await dao.list_recent("688525", 1))[0]
        assert row.volume_shares is None
        assert DailyKlineCache.row_to_bar("688525", row).volume == 17_000_000
    finally:
        await db.close()
