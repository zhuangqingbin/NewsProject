"""In-memory ring buffer for current-day ticks per ticker."""
from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from quote_watcher.feeds.base import QuoteSnapshot


class TickRing:
    def __init__(self, max_per_ticker: int = 1000) -> None:
        self._max = max_per_ticker
        self._data: dict[str, deque[QuoteSnapshot]] = {}

    def append(self, snap: QuoteSnapshot) -> None:
        dq = self._data.setdefault(snap.ticker, deque(maxlen=self._max))
        dq.append(snap)

    def latest(self, ticker: str) -> QuoteSnapshot | None:
        dq = self._data.get(ticker)
        return dq[-1] if dq else None

    def history(self, ticker: str) -> Sequence[QuoteSnapshot]:
        dq = self._data.get(ticker)
        return list(dq) if dq else []

    def size(self, ticker: str) -> int:
        dq = self._data.get(ticker)
        return len(dq) if dq else 0
