"""The ordinary journal entry path was explicitly retired."""


def test_ordinary_journal_ai_path_removed(service):
    client = service[0]
    assert client.get("/v1/journal/retired/ai-review").status_code == 404
    assert client.post("/v1/journal/retired/ai-review", json={"consent": True}).status_code == 404


def test_review_requires_consent_and_uses_current_trade_evidence(service, monkeypatch):
    from test_portfolio import settle
    from test_risk import check, plan, quotes, send

    from app.llm import review_provider
    from app.services import ai_review, journal_ai

    _, sessions, _, settings = service
    settings.ai_review_enabled = True
    settings.ai_review_local_only = False
    client = quotes(service, current=100000)
    draft, checked = check(client, plan_id=plan(service))
    order = send(client, draft, checked, trade_reason="사전 계획 조건 충족").json()
    settle(service, 100000)
    path = f"/v1/journal/orders/{order['order_id']}/ai-review"
    monkeypatch.setattr(review_provider, "connection", lambda *_: {"model": "test"})
    calls = []

    def generate(*args, **kwargs):
        payload = args[6]
        calls.append(payload)
        evidence = {fact["fact_id"]: fact["evidence"] for fact in payload["facts"]}
        assert evidence["fill"]["price_won"] == 100000
        assert evidence["notes"]["trade_reason"] == "사전 계획 조건 충족"
        assert "id" not in evidence["check"]["plan"]
        return {
            "content": {
                key: {"text": "기록한 조건을 주문 전에 다시 확인하세요.", "fact_ids": ["check"]}
                for key in journal_ai.SECTIONS
            },
        }

    monkeypatch.setattr(review_provider, "generate", generate)
    assert client.get(path).json()["status"] == "ready"
    assert client.post(path, json={"consent": False}).status_code == 422
    assert not calls
    assert client.post(path, json={"consent": True}).json()["status"] == "pending"
    ai_review.process_next(sessions, settings)
    ready = client.get(path).json()
    assert ready["status"] == "available", ready
    assert len(ready["result"]["sections"]) == 5
    assert client.post(path, json={"consent": True}).json() == ready
    assert len(calls) == 1

    client.put(f"/v1/orders/{order['order_id']}/note", json={"text": "다음에는 근거 확인"})
    assert client.get(path).json()["status"] == "ready"
    assert client.get("/v1/journal/orders/unknown/ai-review").status_code == 404


def test_deferred_review_rejects_pending_checks_and_includes_reason(service, monkeypatch):
    from test_risk import check, quotes

    from app.llm import review_provider

    client = quotes(service)
    service[3].ai_review_enabled = True
    service[3].ai_review_local_only = False
    monkeypatch.setattr(review_provider, "connection", lambda *_: {"model": "test"})
    _, checked = check(client)
    check_id = checked["check_id"]
    path = f"/v1/journal/deferred/{check_id}/ai-review"
    assert client.get(path).status_code == 404
    response = client.post(f"/v1/orders/check/{check_id}/dismiss", json={"reason": "가격 확인"})
    assert response.status_code == 200
    queued = client.post(path, json={"consent": True}).json()
    facts = {fact["fact_id"]: fact["evidence"] for fact in queued["facts"]}
    assert facts["decision"]["status"] == "deferred"
    assert facts["notes"]["defer_reason"] == "가격 확인"
    assert "fill" not in facts


def test_samples_appear_in_empty_journal_without_counting_as_orders(service, monkeypatch):
    from datetime import datetime

    from app.llm import review_provider
    from app.services import journal as journal_service

    monkeypatch.setattr(
        journal_service, "now", lambda: datetime.fromisoformat("2026-11-17T09:00:00+09:00")
    )

    client, _, _, settings = service
    settings.ai_review_enabled = True
    settings.ai_review_local_only = False
    monkeypatch.setattr(review_provider, "connection", lambda *_: {"model": "test"})

    journal = client.get("/v1/journal?include_pretrade=true").json()
    assert journal["items"] == journal["deferred_checks"] == []
    assert journal["total_orders"] == journal["summary"]["filled_orders"] == 0
    assert journal["summary"]["realized_pnl_won"] == "0"
    assert {row["sample_id"] for row in journal["sample_entries"]} == {
        "planned-buy",
        "planned-exit",
        "deferred-buy",
    }
    path = "/v1/journal/samples/deferred-buy/ai-review"
    assert client.get(path).json()["status"] == "ready"
    response = client.post(path, json={"consent": True})
    assert response.status_code == 200, response.text
    queued = response.json()
    assert queued["status"] == "pending"
    assert {fact["fact_id"] for fact in queued["facts"]} == {"decision", "notes", "check", "market"}
    assert client.get("/v1/journal/samples/unknown/ai-review").status_code == 404
    assert client.get("/v1/journal/orders/deferred-buy/ai-review").status_code == 404
