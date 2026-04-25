from collections.abc import Awaitable, Callable
from typing import Any

CommandHandler = Callable[[list[str], dict[str, Any]], Awaitable[str]]


class CommandDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, name: str) -> Callable[[CommandHandler], CommandHandler]:
        def deco(fn: CommandHandler) -> CommandHandler:
            self._handlers[name] = fn
            return fn
        return deco

    async def handle_text(self, text: str, *,
                           ctx: dict[str, Any]) -> str | None:
        text = text.strip()
        if not text.startswith("/"):
            return None
        parts = text[1:].split()
        if not parts:
            return None
        cmd = parts[0]
        args = parts[1:]
        handler = self._handlers.get(cmd)
        if handler is None:
            return f"未知命令: /{cmd}"
        return await handler(args, ctx)
