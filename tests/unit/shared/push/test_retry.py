# tests/unit/pushers/test_retry.py
import pytest

from shared.push.common.retry import async_retry


@pytest.mark.asyncio
async def test_succeeds_first_try():
    calls = {"n": 0}

    @async_retry(max_attempts=3, backoff_seconds=0.0)
    async def fn():
        calls["n"] += 1
        return "ok"

    assert await fn() == "ok"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_retries_on_exception():
    calls = {"n": 0}

    @async_retry(max_attempts=3, backoff_seconds=0.0, retry_on=(RuntimeError,))
    async def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("x")
        return "ok"

    assert await fn() == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_does_not_retry_on_unmatched_exception():
    @async_retry(max_attempts=3, backoff_seconds=0.0, retry_on=(RuntimeError,))
    async def fn():
        raise ValueError("fatal")

    with pytest.raises(ValueError):
        await fn()
