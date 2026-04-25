# tests/unit/observability/test_alert.py
import pytest
import respx
from httpx import Response

from news_pipeline.observability.alert import AlertLevel, BarkAlerter


@pytest.mark.asyncio
async def test_send_alert_calls_bark():
    async with respx.mock(assert_all_called=True) as mock:
        route = mock.get("https://api.day.app/test/alert-title/alert-body").mock(
            return_value=Response(200, json={"code": 200})
        )
        alerter = BarkAlerter(base_url="https://api.day.app/test")
        ok = await alerter.send("alert-title", "alert-body", level=AlertLevel.WARN)
        assert ok is True
        assert route.called


@pytest.mark.asyncio
async def test_throttle_blocks_repeated_alerts(monkeypatch):
    # Extra values at end so pytest teardown machinery doesn't exhaust the iterator
    _values = [100.0, 100.5, 100.9, 1000.0, 2000.0, 3000.0, 4000.0]
    _idx = [0]

    def _monotonic() -> float:
        v = _values[min(_idx[0], len(_values) - 1)]
        _idx[0] += 1
        return v

    monkeypatch.setattr(
        "news_pipeline.observability.alert.time.monotonic",
        _monotonic,
    )
    async with respx.mock() as mock:
        mock.get(url__regex=r"https://api\.day\.app/test/.*").mock(
            return_value=Response(200, json={"code": 200})
        )
        alerter = BarkAlerter(
            base_url="https://api.day.app/test",
            throttle_seconds=60,
        )
        assert await alerter.send("k", "v") is True
        assert await alerter.send("k", "v") is False
        assert await alerter.send("k", "v") is False
        assert await alerter.send("k", "v") is True
