# src/news_pipeline/pushers/common/burst.py
import time
from collections import defaultdict, deque


class BurstSuppressor:
    def __init__(self, *, window_seconds: int, threshold: int) -> None:
        self._win = window_seconds
        self._th = threshold
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def should_send(self, tickers: list[str]) -> bool:
        now = time.monotonic()
        cutoff = now - self._win
        send = True
        for t in tickers:
            buf = self._buckets[t]
            # expire old entries
            while buf and buf[0] < cutoff:
                buf.popleft()
            if len(buf) >= self._th:
                send = False
        # Only record this attempt when it will actually be sent.
        # If suppressed, do NOT append — otherwise continuous suppressed
        # attempts extend the window forever and suppress never releases.
        if send:
            for t in tickers:
                self._buckets[t].append(now)
        return send
