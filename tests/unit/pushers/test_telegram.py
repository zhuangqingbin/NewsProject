# tests/unit/pushers/test_telegram.py
import pytest
import respx
from httpx import Response

from news_pipeline.common.contracts import (
    Badge,
    CommonMessage,
    Deeplink,
)
from news_pipeline.common.enums import Market
from news_pipeline.pushers.telegram import (
    TelegramPusher,
    md2_escape,
    md2_escape_code,
    md2_escape_link_url,
    md2_escape_text,
)


def _msg() -> CommonMessage:
    return CommonMessage(
        title="NVDA *up* 5%",
        summary="出口管制 [详情]",
        source_label="Reuters",
        source_url="https://reut/x",
        badges=[Badge(text="NVDA", color="blue"), Badge(text="bearish", color="red")],
        chart_url=None,
        deeplinks=[
            Deeplink(label="原文", url="https://reut/x"),
            Deeplink(label="Yahoo", url="https://yhoo/x"),
        ],
        market=Market.US,
    )


def _msg_with_chart() -> CommonMessage:
    return CommonMessage(
        title="NVDA chart",
        summary="K线图",
        source_label="Reuters",
        source_url="https://reut/x",
        badges=[Badge(text="NVDA", color="blue")],
        chart_url=None,
        chart_image=b"\x89PNG\r\n\x1a\nFAKEDATA",
        deeplinks=[],
        market=Market.US,
    )


@pytest.mark.asyncio
async def test_send_escapes_and_returns_ok():
    async with respx.mock() as mock:
        route = mock.post("https://api.telegram.org/botT/sendMessage").mock(
            return_value=Response(200, json={"ok": True})
        )
        p = TelegramPusher(channel_id="tg_us", bot_token="T", chat_id="C")
        result = await p.send(_msg())
        assert result.ok is True
        body = route.calls[0].request.read().decode()
        # MarkdownV2 escaping required
        assert "\\*" in body or "%5C%2A" in body  # the * was escaped
        assert "MarkdownV2" in body


@pytest.mark.asyncio
async def test_send_failure_returns_not_ok():
    async with respx.mock() as mock:
        mock.post("https://api.telegram.org/botT/sendMessage").mock(
            return_value=Response(400, json={"ok": False, "description": "bad"})
        )
        p = TelegramPusher(channel_id="tg_us", bot_token="T", chat_id="C", max_retries=1)
        result = await p.send(_msg())
        assert result.ok is False
        assert result.http_status == 400


@pytest.mark.asyncio
async def test_send_with_chart_image_uses_send_photo():
    # assert_all_called=False because we don't want to register sendMessage at all
    async with respx.mock(assert_all_called=False) as mock:
        send_photo_route = mock.post("https://api.telegram.org/botT/sendPhoto").mock(
            return_value=Response(200, json={"ok": True})
        )
        p = TelegramPusher(channel_id="tg_us", bot_token="T", chat_id="C")
        result = await p.send(_msg_with_chart())
        assert result.ok is True
        # sendPhoto was called
        assert send_photo_route.called
        # Multipart body contains the filename and PNG bytes
        body = send_photo_route.calls[0].request.read()
        assert b"chart.png" in body
        assert b"\x89PNG" in body


# ---------------------------------------------------------------------------
# Fix I9: context-split escaping unit tests
# ---------------------------------------------------------------------------


def test_md2_escape_text_escapes_star():
    """Title with * → escaped as \\* in text context."""
    assert md2_escape_text("NVDA *up*") == r"NVDA \*up\*"


def test_md2_escape_text_escapes_dot_and_parens():
    """Parentheses and dots are escaped in text context."""
    result = md2_escape_text("see (BABA.TW)")
    assert r"\(" in result
    assert r"\)" in result
    assert r"\." in result


def test_md2_escape_code_does_not_escape_dot():
    """Badge ticker BABA.TW inside backticks: dot must NOT be escaped."""
    result = md2_escape_code("BABA.TW")
    assert result == "BABA.TW", f"Unexpected escaping in code context: {result!r}"


def test_md2_escape_code_escapes_backtick():
    """Backtick inside code span must be escaped."""
    result = md2_escape_code("foo`bar")
    assert r"\`" in result


def test_md2_escape_code_does_not_escape_underscore():
    """Underscore must NOT be escaped inside code spans."""
    result = md2_escape_code("some_ticker")
    assert result == "some_ticker"


def test_md2_escape_link_url_escapes_closing_paren():
    """URL containing ) must have it escaped for the link URL context."""
    url = "https://example.com/path(foo)/bar"
    result = md2_escape_link_url(url)
    assert r"\)" in result
    # Opening paren does not need escaping in URL context
    assert "(" in result


def test_md2_escape_link_url_does_not_escape_underscore():
    """Underscore in URLs (very common) must NOT be escaped in link URL context."""
    url = "https://example.com/some_path?q=1"
    result = md2_escape_link_url(url)
    assert "_" in result
    assert r"\_" not in result


def test_md2_escape_backward_compat():
    """md2_escape is a backwards-compat alias for md2_escape_text."""
    text = "hello *world* (test)"
    assert md2_escape(text) == md2_escape_text(text)


def test_render_uses_code_escaping_for_badges():
    """Integration: badge text rendered inside backticks uses code escaping."""
    p = TelegramPusher(channel_id="tg_us", bot_token="T", chat_id="C")
    msg = CommonMessage(
        title="Test",
        summary="summary",
        source_label="src",
        source_url="https://x",
        badges=[Badge(text="BABA.TW", color="blue")],
        chart_url=None,
        deeplinks=[],
        market=Market.US,
    )
    rendered = p._render(msg)
    # Badge should be in backticks and the dot must NOT be escaped
    assert "`BABA.TW`" in rendered


def test_render_escapes_url_closing_paren():
    """Integration: link URL with ) is properly escaped in rendered output."""
    p = TelegramPusher(channel_id="tg_us", bot_token="T", chat_id="C")
    msg = CommonMessage(
        title="Test",
        summary="summary",
        source_label="src",
        source_url="https://x",
        badges=[],
        chart_url=None,
        deeplinks=[Deeplink(label="link", url="https://example.com/foo(bar)")],
        market=Market.US,
    )
    rendered = p._render(msg)
    # The ) in the URL inside (...) must be escaped
    assert r"\)" in rendered
