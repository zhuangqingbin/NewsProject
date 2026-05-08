"""Quote feed contracts."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class QuoteSnapshot:
    ticker: str
    market: str         # "SH" | "SZ" | "BJ"
    name: str
    ts: datetime        # tz-aware Asia/Shanghai
    price: float
    open: float
    high: float
    low: float
    prev_close: float
    volume: int
    amount: float
    bid1: float
    ask1: float

    @property
    def pct_change(self) -> float:
        if self.prev_close == 0:
            return 0.0
        return (self.price - self.prev_close) / self.prev_close * 100


class QuoteFeed(Protocol):
    source_id: str

    async def fetch(self, tickers: list[tuple[str, str]]) -> Sequence[QuoteSnapshot]:
        """tickers: list of (market, ticker) — e.g. [('SH', '600519')]."""
        ...
