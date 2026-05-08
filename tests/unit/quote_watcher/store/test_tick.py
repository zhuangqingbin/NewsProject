from datetime import UTC, datetime

from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.store.tick import TickRing


def make_snap(ticker: str, price: float, ts: int = 0) -> QuoteSnapshot:
    return QuoteSnapshot(
        ticker=ticker, market="SH", name="X",
        ts=datetime.fromtimestamp(ts, tz=UTC),
        price=price, open=0, high=0, low=0, prev_close=price,
        volume=0, amount=0.0, bid1=0, ask1=0,
    )


def test_append_and_latest():
    ring = TickRing(max_per_ticker=3)
    ring.append(make_snap("600519", 100.0, 1))
    ring.append(make_snap("600519", 101.0, 2))
    assert ring.latest("600519").price == 101.0
    assert ring.size("600519") == 2


def test_ring_max_size_evicts_oldest():
    ring = TickRing(max_per_ticker=2)
    ring.append(make_snap("600519", 1.0, 1))
    ring.append(make_snap("600519", 2.0, 2))
    ring.append(make_snap("600519", 3.0, 3))
    assert ring.size("600519") == 2
    assert ring.latest("600519").price == 3.0
    history = ring.history("600519")
    assert [s.price for s in history] == [2.0, 3.0]


def test_no_data_returns_none():
    ring = TickRing()
    assert ring.latest("000001") is None
    assert ring.size("000001") == 0
    assert ring.history("000001") == []


def test_per_ticker_isolation():
    ring = TickRing(max_per_ticker=2)
    ring.append(make_snap("600519", 1.0, 1))
    ring.append(make_snap("000001", 2.0, 2))
    assert ring.latest("600519").price == 1.0
    assert ring.latest("000001").price == 2.0
    assert ring.size("600519") == 1
    assert ring.size("000001") == 1
