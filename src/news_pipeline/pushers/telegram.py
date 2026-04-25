# src/news_pipeline/pushers/telegram.py
import re
from io import BytesIO

import httpx

from news_pipeline.common.contracts import CommonMessage
from news_pipeline.pushers.base import SendResult
from news_pipeline.pushers.common.retry import async_retry

# https://core.telegram.org/bots/api#markdownv2-style
#
# Escaping rules differ by context:
#   - Text / emphasis / bold: all special chars must be escaped
#   - Inside `code` spans: only backtick and backslash
#   - Inside (link_url): only ) and backslash (URL already encoded, _ safe)

# All special chars for regular text context
_MD2_TEXT_SPECIAL = r"_*[]()~`>#+-=|{}.!\\"

# Inside `code` spans: only backtick and backslash need escaping
_MD2_CODE_SPECIAL = r"`\\"

# Inside (link_url): only ) and backslash need escaping
_MD2_LINK_URL_SPECIAL = r")\\"

# Telegram caption limit for sendPhoto
_CAPTION_MAX = 1024


def md2_escape_text(text: str) -> str:
    """Escape all MarkdownV2 special characters for use in text/emphasis/bold context."""
    return re.sub(rf"([{re.escape(_MD2_TEXT_SPECIAL)}])", r"\\\1", text)


def md2_escape_code(text: str) -> str:
    """Escape for use inside backtick code spans — only ` and \\ need escaping."""
    return re.sub(rf"([{re.escape(_MD2_CODE_SPECIAL)}])", r"\\\1", text)


def md2_escape_link_url(url: str) -> str:
    """Escape for use inside link URL parentheses — only ) and \\ need escaping."""
    return re.sub(rf"([{re.escape(_MD2_LINK_URL_SPECIAL)}])", r"\\\1", url)


def md2_escape(text: str) -> str:
    """Escape all MarkdownV2 special chars (text context).

    Deprecated: use md2_escape_text / md2_escape_code / md2_escape_link_url
    for the appropriate context.
    """
    return md2_escape_text(text)


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
        title = md2_escape_text(msg.title)
        summary = md2_escape_text(msg.summary)
        # Badge text is inside backticks — only ` and \\ need escaping
        badges = " ".join(f"`{md2_escape_code(b.text)}`" for b in msg.badges)
        # Link label is in [...] (text context); URL is in (...) (url context)
        links = r"  \| ".join(
            f"[{md2_escape_text(d.label)}]({md2_escape_link_url(str(d.url))})"
            for d in msg.deeplinks
        )
        chart = ""
        if msg.chart_url:
            chart = f"\n\n[📈 chart]({md2_escape_link_url(str(msg.chart_url))})"
        return (
            f"*{title}*\n"
            f"_{md2_escape_text(msg.source_label)}_\n\n"
            f"{summary}\n\n"
            f"{badges}\n\n"
            f"{links}{chart}"
        )
