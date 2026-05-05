import json
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request, Response

_401 = Response(content='{"detail":"Unauthorized"}', status_code=401, media_type="application/json")


def build_app(
    *,
    handlers: Callable[[str, dict[str, Any]], dict],
    feishu_verification_token: str | None = None,
) -> FastAPI:
    """Build the FastAPI command-server.

    Args:
        handlers: callable(source, payload) -> response dict
        feishu_verification_token: Feishu classic verification token (set in
            the Feishu event-subscription console).  When provided, the
            ``token`` field in the request body must match or the request is
            rejected with 401.
    """
    app = FastAPI(title="news_pipeline_cmds")

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.post("/feishu/event")
    async def feishu_event(req: Request) -> Response:
        payload = await req.json()
        if feishu_verification_token is not None:
            body_token = payload.get("token", "")
            if body_token != feishu_verification_token:
                return _401
        result = handlers("feishu", payload)
        return Response(content=json.dumps(result), media_type="application/json")

    return app
