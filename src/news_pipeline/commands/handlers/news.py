from typing import Any

from news_pipeline.commands.dispatcher import CommandDispatcher


def register_news_cmds(d: CommandDispatcher, *, processed_dao: Any) -> None:

    @d.register("news")
    async def news(args: list[str], ctx: dict[str, Any]) -> str:
        if not args:
            return "用法: /news TICKER"
        ticker = args[0]
        items = await processed_dao.list_recent_for_ticker(ticker, limit=10)
        if not items:
            return f"{ticker} 近期无新闻"
        lines = [f"• {p.extracted_at} {p.summary[:120]}" for p in items[:10]]
        return f"{ticker} 近 10 条:\n" + "\n".join(lines)
