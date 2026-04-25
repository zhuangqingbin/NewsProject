# src/news_pipeline/archive/feishu_table.py
from typing import Any

import httpx

from news_pipeline.observability.log import get_logger
from news_pipeline.pushers.common.feishu_auth import FeishuTenantAuth
from news_pipeline.pushers.common.retry import async_retry

log = get_logger(__name__)

# Errcodes that indicate a configuration problem, not a transient failure.
# Retrying won't help; fail fast instead.
_PERMANENT_ERRORS: frozenset[int] = frozenset(
    {
        99991668,  # no permission
        99991661,  # app not found
        1254030,  # table not found
    }
)


class FeishuPermanentError(RuntimeError):
    """Raised when Feishu returns a known-permanent errcode.

    Retry logic must NOT catch this — it indicates a configuration problem
    (missing permission, wrong app/table ID) that retrying cannot fix.
    """

    def __init__(self, message: str, errcode: int) -> None:
        super().__init__(message)
        self.errcode = errcode


class FeishuBitableClient:
    """Wraps 飞书 OpenAPI append_records endpoint."""

    def __init__(
        self,
        *,
        app_token: str,
        table_id: str,
        auth: FeishuTenantAuth,
        timeout: float = 15.0,
    ) -> None:
        self._auth = auth
        self._app_token = app_token
        self._table_id = table_id
        self._timeout = timeout

    @async_retry(
        max_attempts=3,
        backoff_seconds=1.0,
        retry_on=(httpx.HTTPError, RuntimeError),
        exclude_on=(FeishuPermanentError,),
    )
    async def append_record(self, fields: dict[str, Any]) -> str:
        token = await self._auth.get_token()
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self._app_token}"
            f"/tables/{self._table_id}/records"
        )
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={"fields": fields},
            )
            r.raise_for_status()
            data = r.json()
            code = data.get("code")
            if code != 0:
                errcode = int(code) if code is not None else -1
                if errcode in _PERMANENT_ERRORS:
                    # Configuration problem — fail fast, no retry
                    raise FeishuPermanentError(
                        f"feishu bitable permanent error {errcode}: {data}",
                        errcode=errcode,
                    )
                # Token may have expired — invalidate cache so next attempt re-fetches
                if errcode in (99991663, 99991664):
                    self._auth.invalidate()
                raise RuntimeError(f"feishu bitable error {errcode}: {data}")
            return str(data["data"]["record"]["record_id"])
