# src/news_pipeline/observability/alert.py
import time
from enum import StrEnum
from urllib.parse import quote

import httpx

from news_pipeline.observability.log import get_logger

log = get_logger(__name__)


class AlertLevel(StrEnum):
    INFO = "info"
    WARN = "warn"
    URGENT = "urgent"


class BarkAlerter:
    def __init__(
        self,
        base_url: str,
        throttle_seconds: int = 900,
        timeout: float = 5.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._throttle = throttle_seconds
        self._last_sent: dict[str, float] = {}
        self._timeout = timeout

    async def send(self, title: str, body: str, level: AlertLevel = AlertLevel.INFO) -> bool:
        key = f"{level}:{title}"
        now = time.monotonic()
        last = self._last_sent.get(key)
        if last is not None and (now - last) < self._throttle:
            log.debug("alert_throttled", title=title, level=level)
            return False
        self._last_sent[key] = now
        # Bark URL path segments must be percent-encoded; titles/bodies often
        # contain newlines, slashes, Unicode, or other special chars that
        # break url parsers (httpx rejects \n in paths).
        safe_title = quote(title.replace("\n", " ").strip()[:100], safe="")
        safe_body = quote(body.replace("\n", " ").strip()[:500], safe="")
        url = f"{self._base}/{safe_title}/{safe_body}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    log.warning("alert_http_error", status=resp.status_code)
                    return False
        except Exception as e:
            log.warning("alert_exception", error=str(e))
            return False
        return True
