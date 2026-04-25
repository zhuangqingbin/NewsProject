# src/news_pipeline/archive/feishu_table.py
from typing import Any

import httpx

from news_pipeline.observability.log import get_logger
from news_pipeline.pushers.common.feishu_auth import FeishuTenantAuth
from news_pipeline.pushers.common.retry import async_retry

log = get_logger(__name__)


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

    @async_retry(max_attempts=3, backoff_seconds=1.0, retry_on=(httpx.HTTPError,))
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
            if data.get("code") != 0:
                # Token may have expired — invalidate cache
                if data.get("code") in (99991663, 99991664):
                    self._auth.invalidate()
                raise RuntimeError(f"feishu bitable error: {data}")
            return str(data["data"]["record"]["record_id"])
