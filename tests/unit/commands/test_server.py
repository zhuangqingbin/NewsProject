from fastapi.testclient import TestClient

from news_pipeline.commands.server import build_app


def test_health_endpoint():
    app = build_app(handlers=lambda src, payload: {"ok": True, "src": src})
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200


def test_telegram_webhook_dispatches():
    captured = {}

    def handler(src, payload):
        captured["src"] = src
        captured["payload"] = payload
        return {"ok": True}

    app = build_app(handlers=handler)
    client = TestClient(app)
    r = client.post("/tg/webhook", json={"message": {"text": "/list"}})
    assert r.status_code == 200
    assert captured["src"] == "telegram"
