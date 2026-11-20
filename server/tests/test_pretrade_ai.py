import json
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_api import checked

from app.llm import chatgpt
from app.models import AIReview, OrderCheck, now
from app.services import ai_review


@pytest.fixture
def connected(service, monkeypatch):
    service[3].ai_review_enabled = True
    service[3].ai_review_local_only = False
    monkeypatch.setattr(chatgpt, "connection", lambda *_: {"model": "test-model"})
    return service


def test_pretrade_consent_frozen_input_and_worker(connected, monkeypatch):
    client, sessions, uid, settings = connected
    check_id = checked(client)["check_id"]
    path = f"/v1/orders/check/{check_id}/ai-feedback"
    assert client.get(path).json()["status"] == "ready"
    assert client.post(path, json={"consent": False}).status_code == 422
    assert client.post(path, json={"consent": True}).json()["status"] == "pending"
    assert client.post(path, json={"consent": True}).json()["attempts"] == 1
    with sessions() as db:
        record = db.scalar(select(AIReview).where(AIReview.check_id == check_id))
        raw = json.dumps(record.data["input"], ensure_ascii=False)
        assert record.order_id is None and record.run_id is None
        for secret in [uid, check_id]:
            assert secret not in raw
        assert "research_window" in raw
        assert "holding_period" not in raw and "risk_profile" not in raw
        assert "daily_ohlcv" not in raw and "statistics" not in raw
    calls = []

    def generate(*args, **kwargs):
        assert kwargs["web_search"] is True
        calls.append(args)
        return dict(
            content="## 최종 판단: 데이터 부족\n자료 부족으로 판단을 유보합니다.",
            response_model="test-model",
            latency_ms=1,
            search=dict(used=True, completed_calls=1, sources=[]),
        )

    monkeypatch.setattr(chatgpt, "generate", generate)

    class NoHistoryProvider:
        def get_year_history(self, *a, **kw):
            pytest.fail("Must not fetch or save a year of quotes locally")

    ai_review.process_next(sessions, settings, NoHistoryProvider())
    ai_review.process_next(sessions, settings, NoHistoryProvider())
    assert client.get(path).json()["status"] == "available"
    assert len(calls) == 1


def test_prompt_options_replace_instructions_for_new_requests(connected, monkeypatch):
    from app.services import decision_ai, pretrade_ai

    client, sessions, _, settings = connected
    chart_setting = "/v1/ai/prompts/chart"
    order_setting = "/v1/ai/prompts/order"
    chart = "/v1/market/005930/ai-analysis"
    assert client.get(chart_setting).json()["text"] == decision_ai.MARKET_PROMPT
    assert client.get(order_setting).json()["alternate_default"] == pretrade_ai.WEB_ORDER_PROMPT
    assert client.put(chart_setting, json={"text": "  "}).status_code == 422
    assert client.put(chart_setting, json={"text": "첫 번째 차트 프롬프트"}).json()["customized"]
    assert client.post(chart, json={"consent": True}).json()["status"] == "pending"
    assert client.put(chart_setting, json={"text": "두 번째 차트 프롬프트"}).status_code == 200
    assert client.get(chart).json()["status"] == "ready"
    assert client.post(chart, json={"consent": True}).json()["status"] == "pending"
    assert client.put(order_setting, json={"text": "사용자 주문 프롬프트"}).status_code == 200
    check_id = checked(client)["check_id"]
    order = f"/v1/orders/check/{check_id}/ai-feedback"
    assert client.post(order, json={"consent": True}).json()["status"] == "pending"
    calls = []

    def generate(*args, **kwargs):
        calls.append(args[3])
        return dict(
            content="PILOT_SIGNAL=관망\n\n## 결론\n시장 관망",
            response_model="test-model",
            latency_ms=1,
            search=dict(used=True, completed_calls=1, sources=[]),
        )

    monkeypatch.setattr(chatgpt, "generate", generate)
    for _ in range(3):
        ai_review.process_next(sessions, settings)
    assert calls[0].startswith("첫 번째 차트 프롬프트")
    assert calls[1].startswith("두 번째 차트 프롬프트")
    assert calls[2].startswith("사용자 주문 프롬프트")
    assert client.get(chart).json()["result"]["judgment"] == "관망"
    assert (
        client.put(chart_setting, json={"text": None}).json()["text"] == decision_ai.MARKET_PROMPT
    )
    assert client.get(chart).json()["status"] == "ready"


def test_expired_checks_never_generate(connected, monkeypatch):
    client, sessions, _, settings = connected
    check_id = checked(client)["check_id"]
    path = f"/v1/orders/check/{check_id}/ai-feedback"
    client.post(path, json={"consent": True})
    with sessions.begin() as db:
        db.get(OrderCheck, check_id).expires_at = now() - timedelta(seconds=1)
    monkeypatch.setattr(chatgpt, "generate", lambda *_: pytest.fail("Expired quote feedback"))
    ai_review.process_next(sessions, settings)
    assert client.get(path).json()["status"] == "expired"
    assert client.post(path, json={"consent": True}).status_code == 409


def test_automatic_analysis_and_ownership(connected):
    from app.cli import create_user

    client, sessions, _, _ = connected
    last = None
    for i in range(6):
        last = checked(client)["check_id"]
        response = client.post(f"/v1/orders/check/{last}/ai-feedback", json={"consent": True})
        assert response.status_code == 200
    with sessions.begin() as db:
        create_user(db, "other-pretrade@example.com", "other-test-password")
    login = client.post(
        "/v1/auth/login",
        json={"email": "other-pretrade@example.com", "password": "other-test-password"},
    ).json()
    client.headers["Authorization"] = "Bearer " + login["access_token"]
    assert client.get(f"/v1/orders/check/{last}/ai-feedback").status_code == 404


def test_feedback_only_uses_complete_cached_five_minute_bars():
    from datetime import UTC, datetime

    from app.brokers.toss import TossMarketData
    from app.config import Settings

    p = TossMarketData(Settings(database_url="postgresql://unused", _env_file=None))
    start = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)
    bars = [
        dict(
            opened_at=start + timedelta(minutes=i),
            open_won=100,
            high_won=110,
            low_won=90,
            close_won=101,
            volume=10,
            source="toss_kr",
            complete=True,
        )
        for i in range(5)
    ]
    p._feedback_candles["005930"] = bars[:4]
    assert p.get_feedback_candles("005930") == []
    p._feedback_candles["005930"] = bars
    result = p.get_feedback_candles("005930")
    assert len(result) == 1 and result[0]["volume"] == 50
    assert result[0]["complete"] and result[0]["opened_at"] == start
