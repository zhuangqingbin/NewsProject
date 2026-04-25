from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request, Response

_401 = Response(content='{"detail":"Unauthorized"}', status_code=401, media_type="application/json")


def build_app(
    *,
    handlers: Callable[[str, dict[str, Any]], dict],
    tg_secret_token: str | None = None,
    feishu_verification_token: str | None = None,
) -> FastAPI:
    """Build the FastAPI command-server.

    Args:
        handlers: callable(source, payload) -> response dict
        tg_secret_token: value set via Telegram setWebhook secret_token param.
            When provided, the ``X-Telegram-Bot-Api-Secret-Token`` header must
            match or the request is rejected with 401.
        feishu_verification_token: Feishu classic verification token (set in
            the Feishu event-subscription console).  When provided, the
            ``token`` field in the request body must match or the request is
            rejected with 401.
    """
    app = FastAPI(title="news_pipeline_cmds")

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.post("/tg/webhook")
    async def tg_webhook(req: Request) -> Response:
        if tg_secret_token is not None:
            header_val = req.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if header_val != tg_secret_token:
                return _401
        payload = await req.json()
        result = handlers("telegram", payload)
        import json

        return Response(content=json.dumps(result), media_type="application/json")

    @app.post("/feishu/event")
    async def feishu_event(req: Request) -> Response:
        payload = await req.json()
        if feishu_verification_token is not None:
            body_token = payload.get("token", "")
            if body_token != feishu_verification_token:
                return _401
        result = handlers("feishu", payload)
        import json

        return Response(content=json.dumps(result), media_type="application/json")

    return app
