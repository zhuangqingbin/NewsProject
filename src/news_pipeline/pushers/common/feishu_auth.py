# src/news_pipeline/pushers/common/feishu_auth.py
import asyncio
import time

import httpx

from news_pipeline.observability.log import get_logger

log = get_logger(__name__)


class FeishuTenantAuth:
    """Caches tenant_access_token with expiry. Thread- and async-safe."""

    def __init__(self, app_id: str, app_secret: str, timeout: float = 10.0) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._timeout = timeout
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        async with self._lock:
            now = time.monotonic()
            if self._token and now < self._expires_at - 60:
                return self._token
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
                self._token = data["tenant_access_token"]
                self._expires_at = now + float(data.get("expire", 7200))
                log.info("feishu_tenant_token_refreshed")
                return self._token

    def invalidate(self) -> None:
        self._token = None
        self._expires_at = 0.0
