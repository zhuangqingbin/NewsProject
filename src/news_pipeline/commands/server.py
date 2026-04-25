from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request


def build_app(*, handlers: Callable[[str, dict[str, Any]], dict]) -> FastAPI:
    app = FastAPI(title="news_pipeline_cmds")

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.post("/tg/webhook")
    async def tg_webhook(req: Request) -> dict:
        return handlers("telegram", await req.json())

    @app.post("/feishu/event")
    async def feishu_event(req: Request) -> dict:
        return handlers("feishu", await req.json())

    return app
