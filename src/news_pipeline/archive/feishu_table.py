# src/news_pipeline/archive/feishu_table.py
from typing import Any

import httpx

from news_pipeline.observability.log import get_logger
from news_pipeline.pushers.common.retry import async_retry

log = get_logger(__name__)


class FeishuBitableClient:
    """Wraps 飞书 OpenAPI append_records endpoint."""

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        app_token: str,
        table_id: str,
        timeout: float = 15.0,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._app_token = app_token
        self._table_id = table_id
        self._timeout = timeout
        self._cached_token: str | None = None

    async def _tenant_token(self) -> str:
        if self._cached_token is not None:
            return self._cached_token
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(
                url,
                json={"app_id": self._app_id, "app_secret": self._app_secret},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("code") != 0:
                raise RuntimeError(f"feishu auth failed: {data}")
            self._cached_token = data["tenant_access_token"]
            return self._cached_token

    @async_retry(max_attempts=3, backoff_seconds=1.0, retry_on=(httpx.HTTPError,))
    async def append_record(self, fields: dict[str, Any]) -> str:
        token = await self._tenant_token()
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
            if data.get("code") != 0:
                # Token may have expired — invalidate cache
                if data.get("code") in (99991663, 99991664):
                    self._cached_token = None
                raise RuntimeError(f"feishu bitable error: {data}")
            return str(data["data"]["record"]["record_id"])
