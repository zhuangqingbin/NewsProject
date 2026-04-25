# src/news_pipeline/pushers/telegram.py
import re
from io import BytesIO

import httpx

from news_pipeline.common.contracts import CommonMessage
from news_pipeline.pushers.base import SendResult
from news_pipeline.pushers.common.retry import async_retry

# https://core.telegram.org/bots/api#markdownv2-style
_MD2_SPECIAL = r"_*[]()~`>#+-=|{}.!\\"

# Telegram caption limit for sendPhoto
_CAPTION_MAX = 1024


def md2_escape(text: str) -> str:
    return re.sub(rf"([{re.escape(_MD2_SPECIAL)}])", r"\\\1", text)


class TelegramPusher:
    def __init__(
        self,
        *,
        channel_id: str,
        bot_token: str,
        chat_id: str,
        timeout: float = 10.0,
        max_retries: int = 3,
    ) -> None:
        self.channel_id = channel_id
        self._bot = bot_token
        self._chat = chat_id
        self._timeout = timeout
        self._max = max_retries

    async def send(self, msg: CommonMessage) -> SendResult:
        if msg.chart_image is not None:
            return await self._send_photo(msg)
        return await self._send_message(msg)

    async def _send_message(self, msg: CommonMessage) -> SendResult:
        text = self._render(msg)
        url = f"https://api.telegram.org/bot{self._bot}/sendMessage"
        body = {
            "chat_id": self._chat,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": False,
        }

        @async_retry(
            max_attempts=self._max,
            backoff_seconds=1.0,
            retry_on=(httpx.HTTPError,),
        )
        async def _post() -> tuple[int, str]:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(url, json=body)
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        message=f"HTTP {r.status_code}",
                        request=r.request,
                        response=r,
                    )
                return r.status_code, r.text

        try:
            status, resp_text = await _post()
        except httpx.HTTPError as e:
            return SendResult(ok=False, http_status=None, response_body=str(e), retries=self._max)
        return SendResult(
            ok=(status == 200), http_status=status, response_body=resp_text, retries=0
        )

    async def _send_photo(self, msg: CommonMessage) -> SendResult:
        """Send chart_image as a photo using multipart/form-data (sendPhoto API).

        Caption is truncated to 1024 chars (Telegram limit).
        """
        assert msg.chart_image is not None
        caption = self._render(msg)[:_CAPTION_MAX]
        url = f"https://api.telegram.org/bot{self._bot}/sendPhoto"

        @async_retry(
            max_attempts=self._max,
            backoff_seconds=1.0,
            retry_on=(httpx.HTTPError,),
        )
        async def _post() -> tuple[int, str]:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(
                    url,
                    data={"chat_id": self._chat, "caption": caption, "parse_mode": "MarkdownV2"},
                    files={"photo": ("chart.png", BytesIO(msg.chart_image), "image/png")},  # type: ignore[arg-type]
                )
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        message=f"HTTP {r.status_code}",
                        request=r.request,
                        response=r,
                    )
                return r.status_code, r.text

        try:
            status, resp_text = await _post()
        except httpx.HTTPError as e:
            return SendResult(ok=False, http_status=None, response_body=str(e), retries=self._max)
        return SendResult(
            ok=(status == 200), http_status=status, response_body=resp_text, retries=0
        )

    def _render(self, msg: CommonMessage) -> str:
        title = md2_escape(msg.title)
        summary = md2_escape(msg.summary)
        badges = " ".join(f"`{md2_escape(b.text)}`" for b in msg.badges)
        links = r"  \| ".join(f"[{md2_escape(d.label)}]({d.url})" for d in msg.deeplinks)
        chart = ""
        if msg.chart_url:
            chart = f"\n\n[📈 chart]({msg.chart_url})"
        return (
            f"*{title}*\n"
            f"_{md2_escape(msg.source_label)}_\n\n"
            f"{summary}\n\n"
            f"{badges}\n\n"
            f"{links}{chart}"
        )
