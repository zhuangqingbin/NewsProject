import asyncio

from news_pipeline.commands.dispatcher import CommandDispatcher


def test_register_and_dispatch_text():
    d = CommandDispatcher()
    seen = {}

    @d.register("watch")
    async def watch(args, ctx):
        seen["args"] = args
        return "watched"

    out = asyncio.run(d.handle_text("/watch NVDA TSLA", ctx={}))
    assert out == "watched"
    assert seen["args"] == ["NVDA", "TSLA"]


def test_unknown_command():
    d = CommandDispatcher()
    out = asyncio.run(d.handle_text("/nope", ctx={}))
    assert "未知" in out or "unknown" in out


def test_non_command_text_ignored():
    d = CommandDispatcher()
    out = asyncio.run(d.handle_text("hello", ctx={}))
    assert out is None
