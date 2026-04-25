# tests/unit/archive/test_feishu_table.py
"""Tests for FeishuBitableClient retry / permanent-error behavior (Fix I2)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from news_pipeline.archive.feishu_table import (
    _PERMANENT_ERRORS,
    FeishuBitableClient,
    FeishuPermanentError,
)


def _make_client(auth: object) -> FeishuBitableClient:
    return FeishuBitableClient(
        app_token="app123",
        table_id="tbl456",
        auth=auth,  # type: ignore[arg-type]
    )


def _mock_auth(token: str = "tok") -> MagicMock:
    auth = MagicMock()
    auth.get_token = AsyncMock(return_value=token)
    auth.invalidate = MagicMock()
    return auth


# ---------------------------------------------------------------------------
# Permanent error (99991668 = no permission) — should raise immediately,
# with NO retry (call count must be exactly 1).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_permanent_error_no_retry():
    """errcode 99991668 → FeishuPermanentError, no retry (1 HTTP call)."""
    auth = _mock_auth()
    client = _make_client(auth)

    call_count = 0

    async def _fake_post(*args: object, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"code": 99991668, "msg": "no permission"})
        return resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_acm = MagicMock()
        mock_acm.__aenter__ = AsyncMock(return_value=mock_acm)
        mock_acm.__aexit__ = AsyncMock(return_value=False)
        mock_acm.post = AsyncMock(side_effect=_fake_post)
        mock_client_cls.return_value = mock_acm

        with pytest.raises(FeishuPermanentError) as exc_info:
            await client.append_record({"title": "test"})

    assert exc_info.value.errcode == 99991668
    assert call_count == 1, f"Expected 1 call (no retry), got {call_count}"
    # invalidate should NOT be called for permanent errors
    auth.invalidate.assert_not_called()


@pytest.mark.asyncio
async def test_permanent_error_is_subclass_of_runtime_error():
    """FeishuPermanentError must be a RuntimeError subclass."""
    err = FeishuPermanentError("test", errcode=99991668)
    assert isinstance(err, RuntimeError)
    assert err.errcode == 99991668


def test_permanent_errors_constant():
    """_PERMANENT_ERRORS must contain the three documented errcodes."""
    assert 99991668 in _PERMANENT_ERRORS  # no permission
    assert 99991661 in _PERMANENT_ERRORS  # app not found
    assert 1254030 in _PERMANENT_ERRORS  # table not found


# ---------------------------------------------------------------------------
# Transient error (99991663 = token expired) — should invalidate + retry.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_expired_invalidates_and_retries():
    """errcode 99991663 → invalidate() called, retries, then succeeds on attempt 2."""
    auth = _mock_auth()
    client = _make_client(auth)

    call_count = 0

    async def _fake_post(*args: object, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if call_count == 1:
            resp.json = MagicMock(return_value={"code": 99991663, "msg": "token expired"})
        else:
            resp.json = MagicMock(
                return_value={
                    "code": 0,
                    "data": {"record": {"record_id": "rec_abc"}},
                }
            )
        return resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_acm = MagicMock()
        mock_acm.__aenter__ = AsyncMock(return_value=mock_acm)
        mock_acm.__aexit__ = AsyncMock(return_value=False)
        mock_acm.post = AsyncMock(side_effect=_fake_post)
        mock_client_cls.return_value = mock_acm

        # Patch asyncio.sleep so test doesn't actually wait
        with patch("asyncio.sleep", new_callable=AsyncMock):
            record_id = await client.append_record({"title": "test"})

    assert record_id == "rec_abc"
    assert call_count == 2, f"Expected 2 calls (1 retry), got {call_count}"
    auth.invalidate.assert_called_once()
