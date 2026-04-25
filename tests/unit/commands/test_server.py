from fastapi.testclient import TestClient

from news_pipeline.commands.server import build_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _handler(src, payload):
    return {"ok": True, "src": src}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_endpoint():
    app = build_app(handlers=_handler)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Telegram webhook — no auth configured (open, backward compat)
# ---------------------------------------------------------------------------


def test_telegram_webhook_dispatches_without_auth():
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


# ---------------------------------------------------------------------------
# Telegram webhook — auth enabled
# ---------------------------------------------------------------------------


def test_telegram_webhook_returns_401_when_token_missing():
    app = build_app(handlers=_handler, tg_secret_token="correct-token")
    client = TestClient(app)
    r = client.post("/tg/webhook", json={"message": {"text": "/list"}})
    assert r.status_code == 401


def test_telegram_webhook_returns_401_when_token_wrong():
    app = build_app(handlers=_handler, tg_secret_token="correct-token")
    client = TestClient(app)
    r = client.post(
        "/tg/webhook",
        json={"message": {"text": "/list"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-token"},
    )
    assert r.status_code == 401


def test_telegram_webhook_returns_200_when_token_correct():
    app = build_app(handlers=_handler, tg_secret_token="correct-token")
    client = TestClient(app)
    r = client.post(
        "/tg/webhook",
        json={"message": {"text": "/list"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "correct-token"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ---------------------------------------------------------------------------
# Feishu event — no auth configured (open)
# ---------------------------------------------------------------------------


def test_feishu_event_dispatches_without_auth():
    captured = {}

    def handler(src, payload):
        captured["src"] = src
        return {"ok": True}

    app = build_app(handlers=handler)
    client = TestClient(app)
    r = client.post("/feishu/event", json={"type": "url_verification", "token": "anything"})
    assert r.status_code == 200
    assert captured["src"] == "feishu"


# ---------------------------------------------------------------------------
# Feishu event — auth enabled
# ---------------------------------------------------------------------------


def test_feishu_event_returns_401_when_token_missing():
    app = build_app(handlers=_handler, feishu_verification_token="correct-token")
    client = TestClient(app)
    r = client.post("/feishu/event", json={"type": "url_verification"})
    assert r.status_code == 401


def test_feishu_event_returns_401_when_token_wrong():
    app = build_app(handlers=_handler, feishu_verification_token="correct-token")
    client = TestClient(app)
    r = client.post(
        "/feishu/event",
        json={"type": "url_verification", "token": "wrong-token"},
    )
    assert r.status_code == 401


def test_feishu_event_returns_200_when_token_correct():
    app = build_app(handlers=_handler, feishu_verification_token="correct-token")
    client = TestClient(app)
    r = client.post(
        "/feishu/event",
        json={"type": "url_verification", "token": "correct-token"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
