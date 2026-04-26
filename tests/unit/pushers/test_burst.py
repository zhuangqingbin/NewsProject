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


def test_window_expiry_releases_suppression(monkeypatch):
    """After window expires, sending resumes even after prior burst suppression."""
    # 3 sends fill a 300s window: t=1000, 1100, 1200
    # 4th attempt at t=1250 is suppressed (within window)
    # 5th attempt at t=1600 is after 300s window from first send → resumes
    seq = iter([1000.0, 1100.0, 1200.0, 1250.0, 1600.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(seq))
    s = BurstSuppressor(window_seconds=300, threshold=3)
    assert s.should_send(["NVDA"]) is True  # t=1000, buf=[1000]
    assert s.should_send(["NVDA"]) is True  # t=1100, buf=[1000,1100]
    assert s.should_send(["NVDA"]) is True  # t=1200, buf=[1000,1100,1200]
    assert s.should_send(["NVDA"]) is False  # t=1250, suppressed - buf unchanged
    # t=1600: cutoff=1300, so 1000 and 1100 expire → buf=[1200] → len<3 → send
    assert s.should_send(["NVDA"]) is True


def test_suppressed_attempts_do_not_extend_window(monkeypatch):
    """Continuous suppressed calls every 60s MUST eventually release.

    Bug in old code: buf.append(now) ran even when suppressed, so the window
    kept resetting and the ticker was suppressed forever.
    """
    # Fill the burst window: threshold=3, window=300s
    # Sends at t=0, 60, 120 → buf=[0,60,120], len==3
    # Suppressed calls at t=180, 240, 300, 360 (every 60s) - should NOT extend window
    # At t=360: cutoff=60, so t=0 and t=60 expire → buf=[120] → len<3 → send allowed
    seq = iter([0.0, 60.0, 120.0, 180.0, 240.0, 300.0, 360.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(seq))
    s = BurstSuppressor(window_seconds=300, threshold=3)
    assert s.should_send(["TSLA"]) is True  # t=0
    assert s.should_send(["TSLA"]) is True  # t=60
    assert s.should_send(["TSLA"]) is True  # t=120, buf=[0,60,120]
    assert s.should_send(["TSLA"]) is False  # t=180, suppressed
    assert s.should_send(["TSLA"]) is False  # t=240, suppressed
    assert s.should_send(["TSLA"]) is False  # t=300, suppressed (cutoff=0, all 3 still in)
    # t=360: cutoff=60 → expire t=0 → buf=[60,120] → len=2 < 3 → send
    assert s.should_send(["TSLA"]) is True
