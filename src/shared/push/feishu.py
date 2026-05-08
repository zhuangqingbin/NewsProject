# src/news_pipeline/pushers/feishu.py
import hashlib
import hmac
import time
from base64 import b64encode

import httpx

from news_pipeline.common.contracts import CommonMessage
from shared.push.base import SendResult
from shared.push.common.retry import async_retry

_BADGE_COLOR_MAP = {
    "red": "red",
    "green": "green",
    "yellow": "yellow",
    "blue": "blue",
    "gray": "grey",
}


class FeishuPusher:
    def __init__(
        self,
        *,
        channel_id: str,
        webhook: str,
        sign_secret: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
    ) -> None:
        self.channel_id = channel_id
        self._webhook = webhook
        self._secret = sign_secret
        self._timeout = timeout
        self._max = max_retries

    async def send(self, msg: CommonMessage) -> SendResult:
        body = self._build_card(msg)
        if self._secret:
            ts = str(int(time.time()))
            body["timestamp"] = ts
            body["sign"] = self._sign(ts)

        @async_retry(
            max_attempts=self._max,
            backoff_seconds=1.0,
            retry_on=(httpx.HTTPError,),
        )
        async def _post() -> tuple[int, str]:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(self._webhook, json=body)
                return r.status_code, r.text

        try:
            status, resp = await _post()
        except httpx.HTTPError as e:
            return SendResult(ok=False, http_status=None, response_body=str(e), retries=self._max)
        ok = status == 200 and '"code":0' in resp
        return SendResult(ok=ok, http_status=status, response_body=resp, retries=0)

    def _sign(self, timestamp: str) -> str:
        """Compute Feishu custom-bot message signature.

        Algorithm per Feishu official docs (custom bot security settings):
        https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot

        The HMAC key is ``"{timestamp}\\n{secret}"`` encoded as UTF-8; the
        message is empty (``b""`` — the default when no ``msg`` is passed to
        ``hmac.new``).  The digest is SHA-256, base64-encoded.

        Feishu's published Python sample::

            string_to_sign = '{}\\n{}'.format(timestamp, secret)
            hmac_code = hmac.new(
                string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
            ).digest()
            sign = base64.b64encode(hmac_code).decode('utf-8')

        This implementation is identical to that sample and has been verified
        correct against a known test vector (see test_feishu_sign.py).
        """
        string_to_sign = f"{timestamp}\n{self._secret}"
        h = hmac.new(string_to_sign.encode(), digestmod=hashlib.sha256)
        return b64encode(h.digest()).decode()

    def _build_card(self, msg: CommonMessage) -> dict:  # type: ignore[type-arg]
        # template color = first badge color (sentiment usually)
        first_color = _BADGE_COLOR_MAP.get(
            msg.badges[0].color if msg.badges else "gray",
            "grey",
        )
        if msg.digest_items:
            body_text = "\n".join(
                f"- [{it.source_label}]({it.url}) {it.summary}" for it in msg.digest_items
            )
        else:
            body_text = (
                f"**{msg.summary}**\n\n"
                + " ".join(f"`{b.text}`" for b in msg.badges)
                + "\n\n"
                + " | ".join(f"[{d.label}]({d.url})" for d in msg.deeplinks)
            )
        elements: list[dict] = [  # type: ignore[type-arg]
            {"tag": "div", "text": {"tag": "lark_md", "content": body_text}},
        ]
        # chart_image is silently ignored for Feishu (no self-built app image upload)
        # chart_url fallback (deprecated, kept for legacy configs)
        if msg.chart_url:
            elements.append(
                {
                    "tag": "img",
                    "img_key": str(msg.chart_url),
                    "alt": {"tag": "plain_text", "content": "chart"},
                }
            )
        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": msg.title[:128]},
                    "template": first_color,
                },
                "elements": elements,
            },
        }
