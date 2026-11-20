from fastapi.testclient import TestClient
from test_api import checked

from app.api import create_app
from app.llm import chatgpt
from app.services import ai_review


def test_participant_web_and_server_ai(service, monkeypatch, tmp_path):
    signed_in, sessions, _, settings = service
    origin = "https://demo.example.test"
    settings.web_build_dir = tmp_path
    settings.allowed_origins = [origin]
    settings.ai_review_provider = "openai_api"
    settings.ai_review_enabled = True
    (tmp_path / "index.html").write_text("<title>TradePilot</title>", encoding="utf-8")
    browser = TestClient(
        create_app(settings, sessions),
        base_url=origin,
        headers={**signed_in.headers, "Origin": origin},
    )
    assert "TradePilot" in browser.get("/").text
    assert browser.get("/health/live").status_code == 200
    assert browser.get("/v1/ai/connection").json()["status"] == "not_connected"
    settings.openai_api_key = type(settings.database_url)("test-api-key")
    assert browser.get("/v1/ai/connection").json()["command"] is None

    ticket = browser.post("/v1/ws-ticket").json()["ticket"]
    with browser.websocket_connect(f"/v1/ws?ticket={ticket}") as ws:
        ws.send_json({"type": "subscribe", "channel": "quotes"})
        assert ws.receive_json()["type"] == "quote"

    def generate(*args, **kwargs):
        assert kwargs["api_key"] == "test-api-key"
        assert kwargs["web_search"] is True
        return dict(
            content="PILOT_SIGNAL=관망\n\n## 결론\n시세를 다시 확인하세요.",
            response_model=settings.openai_model,
            search=dict(used=True, completed_calls=1, sources=[]),
        )

    monkeypatch.setattr(chatgpt, "generate", generate)
    path = f"/v1/orders/check/{checked(browser)['check_id']}/ai-feedback"
    assert browser.post(path, json={"consent": True}).json()["status"] == "pending"
    ai_review.process_next(sessions, settings)
    result = browser.get(path).json()
    assert result["status"] == "available"
    assert result["provider"] == "openai_api"
    assert result["result"]["judgment"] == "관망"
