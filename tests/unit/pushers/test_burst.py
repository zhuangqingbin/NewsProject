# tests/unit/pushers/test_burst.py
import time

from news_pipeline.pushers.common.burst import BurstSuppressor


def test_below_threshold_passes(monkeypatch):
    times = iter([1000.0, 1010.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(times))
    s = BurstSuppressor(window_seconds=300, threshold=3)
    assert s.should_send(["NVDA"]) is True
    assert s.should_send(["NVDA"]) is True


def test_at_threshold_suppresses(monkeypatch):
    seq = iter([1000.0, 1100.0, 1200.0, 1250.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(seq))
    s = BurstSuppressor(window_seconds=300, threshold=3)
    assert s.should_send(["NVDA"]) is True
    assert s.should_send(["NVDA"]) is True
    assert s.should_send(["NVDA"]) is True
    assert s.should_send(["NVDA"]) is False
