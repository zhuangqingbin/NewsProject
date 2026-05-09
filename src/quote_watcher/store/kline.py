"""DailyKlineCache: akshare daily K loader + persistent cache for indicator rules."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta

import akshare as ak
import pandas as pd

from quote_watcher.storage.dao.quote_bars import QuoteBarsDailyDAO
from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.storage.models import QuoteBarDaily
from shared.observability.log import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class DailyBar:
    ticker: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    prev_close: float
    volume: int
    amount: float


_BarTuple = tuple[date, float, float, float, float, float, int, float]


def _ak_df_to_bars(ticker: str, df: pd.DataFrame) -> list[_BarTuple]:
    """Convert akshare DataFrame to upsert tuples.

    Tuple layout: (date, open, high, low, close, prev_close, volume, amount).
    prev_close is derived from previous row's close. First row prev_close = its own close
    (no prior data; rules requiring it should look at row[1:] for safety).
    """
    rows: list[_BarTuple] = []
    if df.empty:
        return rows
    df = df.sort_values("日期")
    closes = df["收盘"].astype(float).tolist()
    dates = df["日期"].tolist()
    opens = df["开盘"].astype(float).tolist()
    highs = df["最高"].astype(float).tolist()
    lows = df["最低"].astype(float).tolist()
    volumes = df["成交量"].astype(int).tolist()
    amounts = df["成交额"].astype(float).tolist()
    prev_closes = [closes[0], *closes[:-1]]
    for i, d in enumerate(dates):
        d_obj = d if isinstance(d, date) else pd.to_datetime(d).date()
        rows.append((
            d_obj, opens[i], highs[i], lows[i], closes[i], prev_closes[i],
            volumes[i], amounts[i],
        ))
    return rows


class DailyKlineCache:
    def __init__(self, db: QuoteDatabase) -> None:
        self._dao = QuoteBarsDailyDAO(db)

    async def load_for(
        self, tickers: list[str], days: int = 250,
    ) -> dict[str, list[DailyBar]]:
        out: dict[str, list[DailyBar]] = {}
        for ticker in tickers:
            cached = await self._dao.list_recent(ticker, days)
            if len(cached) >= days:
                out[ticker] = [self._row_to_bar(ticker, r) for r in cached]
                continue
            # Cold or partial cache → call akshare
            try:
                end = date.today()
                start = end - timedelta(days=days * 2)  # extra buffer for non-trading days
                df = await asyncio.to_thread(
                    ak.stock_zh_a_hist,
                    symbol=ticker,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
                )
            except Exception as e:
                log.warning("kline_fetch_failed", ticker=ticker, error=str(e))
                out[ticker] = []
                continue
            tuples = _ak_df_to_bars(ticker, df)
            await self._dao.upsert_many(ticker, tuples)
            cached = await self._dao.list_recent(ticker, days)
            out[ticker] = [self._row_to_bar(ticker, r) for r in cached]
        return out

    async def get_cached(self, ticker: str, days: int = 250) -> list[DailyBar]:
        rows = await self._dao.list_recent(ticker, days)
        return [self._row_to_bar(ticker, r) for r in rows]

    @staticmethod
    def _row_to_bar(ticker: str, row: QuoteBarDaily) -> DailyBar:
        return DailyBar(
            ticker=ticker,
            trade_date=row.trade_date,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            prev_close=row.prev_close,
            volume=row.volume,
            amount=row.amount,
        )
