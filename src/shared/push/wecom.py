# src/news_pipeline/pushers/wecom.py
import httpx

from shared.common.contracts import CommonMessage
from shared.push.base import SendResult
from shared.push.common.retry import async_retry


class WecomPusher:
    def __init__(
        self,
        *,
        channel_id: str,
        webhook: str,
        timeout: float = 10.0,
        max_retries: int = 3,
    ) -> None:
        self.channel_id = channel_id
        self._webhook = webhook
        self._timeout = timeout
        self._max = max_retries

    async def send(self, msg: CommonMessage) -> SendResult:
        body = {
            "msgtype": "markdown",
            "markdown": {"content": self._render(msg)},
        }

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
        ok = status == 200 and '"errcode":0' in resp
        return SendResult(ok=ok, http_status=status, response_body=resp, retries=0)

    def _render(self, msg: CommonMessage) -> str:
        if msg.digest_items:
            items = "\n".join(
                f"- [{it.source_label}]({it.url}) {it.summary}" for it in msg.digest_items
            )
            return f"**{msg.title}**\n\n{items}"
        badges = " ".join(f"`{b.text}`" for b in msg.badges)
        links = " | ".join(f"[{d.label}]({d.url})" for d in msg.deeplinks)
        return f"**{msg.title}**\n> {msg.source_label}\n\n{msg.summary}\n\n{badges}\n\n{links}"
