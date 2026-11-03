import copy
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_replay import act, key

from app.llm import chatgpt
from app.models import AIReview, ReplayCase, ReplayRun, now
from app.services import ai_review


@pytest.fixture
def setup(service):
    client, sessions, uid, _ = service
    case = client.post("/v1/replay/practice").json()
    run = client.post(
        f"/v1/replay/cases/{case['id']}/runs", json={"request_id": key(), "pilot_enabled": True}
    ).json()
    return client, sessions, uid, case, run


@pytest.fixture
def paired(setup, monkeypatch):
    client, sessions, uid, case, run = setup
    # Existing service fixture exposes mutable settings via FastAPI endpoint closures.
    first = act(client, run, "finish")
    second = client.post(
        f"/v1/replay/cases/{case['id']}/runs",
        json={"request_id": key(), "pilot_enabled": False, "paired_run_id": first["id"]},
    ).json()
    second = act(client, second, "finish")
    monkeypatch.setattr(chatgpt, "connection", lambda *_: dict(model="test-fixed-model"))
    return client, sessions, uid, first, second


def enable(service):
    settings = service[3]
    settings.ai_review_enabled = True
    settings.ai_review_local_only = False
    return settings


def output(payload):
    return dict(
        content=dict(
            observations=[
                dict(
                    fact_id="plan",
                    interpretation="계획 평가 여부를 구분해 볼 수 있습니다.",
                    reflection_question="다음 거래 전에 어떤 진입 조건을 정할 수 있을까요?",
                )
            ],
            limitation="행동 집계만으로 예방 효과나 감정을 확정할 수 없습니다.",
        ),
        response_id="test-response",
        response_model="test-snapshot",
        usage={"input_tokens": 100},
        latency_ms=5,
    )


def test_pair_must_finish_and_no_external_call_before_consent(setup, service, monkeypatch):
    client, _, _, case, run = setup
    enable(service)
    monkeypatch.setattr(
        chatgpt, "connection", lambda *_: pytest.fail("No credentials before pair end")
    )
    url = f"/v1/replay/runs/{run['id']}/ai-review"
    assert client.get(url).json()["reason"] == "pair_incomplete"
    assert client.post(url, json={"consent": True}).status_code == 409
    first = act(client, run, "finish")
    assert client.get(url).json()["reason"] == "pair_incomplete"
    client.post(
        f"/v1/replay/cases/{case['id']}/runs",
        json={"request_id": key(), "pilot_enabled": False, "paired_run_id": first["id"]},
    )
    assert client.get(url).json()["reason"] == "pair_incomplete"
    assert client.post(url, json={"consent": False}).status_code == 422
    assert client.post(url, json={"consent": True, "prompt": "override"}).status_code == 422


def test_frozen_anonymous_input_cached_result_and_export(paired, service, monkeypatch):
    client, sessions, uid, run, _ = paired
    settings = enable(service)
    url = f"/v1/replay/runs/{run['id']}/ai-review"
    assert client.get(url).json()["status"] == "ready"
    original = client.get(f"/v1/replay/runs/{run['id']}/export").json()["evidence"]["state"]
    calls = []

    def generate(directory, owner, model, instructions, payload, schema):
        calls.append(payload)
        assert owner == uid and model == "test-fixed-model"
        assert "properties" in schema and "TradePilot" in instructions
        return output(payload)

    monkeypatch.setattr(chatgpt, "generate", generate)
    first = client.post(url, json={"consent": True}).json()
    assert first["status"] == "pending"
    assert client.post(url, json={"consent": True}).json()["attempts"] == 1
    ai_review.process_next(sessions, settings)
    ready = client.get(url).json()
    assert (
        ready["status"] == "available" and ready["result"]["observations"][0]["fact_id"] == "plan"
    )
    assert ready["response_model"] == "test-snapshot"
    assert client.post(url, json={"consent": True}).json() == ready
    ai_review.process_next(sessions, settings)
    assert len(calls) == 1
    assert set(calls[0]) == {"schema", "facts"}
    assert all(set(f) == {"fact_id", "text"} for f in calls[0]["facts"])
    evidence = client.get(f"/v1/replay/runs/{run['id']}/export").json()["evidence"]
    assert evidence["state"] == original
    assert evidence["ai_review"]["result"] == ready["result"]
    assert evidence["ai_review"]["evidence"]["prompt_version"] == ai_review.VERSION
    assert "access_token" not in json.dumps(evidence["ai_review"])


def test_anonymous_facts_ignore_names_future_prices_and_reasons(paired):
    _, sessions, _, run, _ = paired
    with sessions.begin() as db:
        r = db.get(ReplayRun, run["id"])
        c = db.get(ReplayCase, r.case_id)
        expected = ai_review.frozen_input(c, r)
        config = copy.deepcopy(c.config)
        config.update(name="SECRET EVENT 2024", symbol="SECRET SYMBOL", provenance="PRIVATE SOURCE")
        c.config = config
        state = copy.deepcopy(r.state)
        # No reason text or event identity can enter the allowlisted input.
        state["decision_reason"] = "SECRET PERSONAL REASON"
        r.state = state
        assert ai_review.frozen_input(c, r) == expected
        assert "SECRET" not in json.dumps(expected)


def test_errors_explicit_retry_cap_and_no_fake_success(paired, service, monkeypatch):
    client, sessions, _, run, _ = paired
    settings = enable(service)
    url = f"/v1/replay/runs/{run['id']}/ai-review"

    def fail(*_):
        raise chatgpt.ReviewError("usage_limit")

    monkeypatch.setattr(chatgpt, "generate", fail)
    for attempt in (1, 2):
        assert client.post(url, json={"consent": True}).json()["attempts"] == attempt
        ai_review.process_next(sessions, settings)
        result = client.get(url).json()
        assert result["status"] == "failed" and result["result"] is None
        assert result["can_retry"] == (attempt == 1)
    assert client.post(url, json={"consent": True}).status_code == 429


def test_invalid_fact_reference_fails_and_leaves_rule_feedback(paired, service, monkeypatch):
    client, sessions, _, run, _ = paired
    settings = enable(service)

    def invalid(*args):
        value = output(args[4])
        value["content"]["observations"][0]["fact_id"] = "invented"
        return value

    monkeypatch.setattr(chatgpt, "generate", invalid)
    url = f"/v1/replay/runs/{run['id']}/ai-review"
    client.post(url, json={"consent": True})
    ai_review.process_next(sessions, settings)
    assert client.get(url).json()["status"] == "failed"
    assert client.get(f"/v1/replay/runs/{run['id']}").json()["summary"]["warning_types"]


def test_owner_isolation_and_local_only(paired, service):
    client, _, _, run, _ = paired
    settings = enable(service)
    url = f"/v1/replay/runs/{run['id']}/ai-review"
    assert client.get(f"/v1/replay/runs/{uuid4()}/ai-review").status_code == 404
    assert (
        client.post(
            "/v1/auth/signup",
            json={
                "email": "other-ai@example.com",
                "password": "test-password-123",
                "password_confirmation": "test-password-123",
            },
        ).status_code
        == 201
    )
    token = client.post(
        "/v1/auth/login", json={"email": "other-ai@example.com", "password": "test-password-123"}
    ).json()["access_token"]
    assert client.get(url, headers={"Authorization": f"Bearer {token}"}).status_code == 404
    settings.ai_review_local_only = True
    assert client.get(url).status_code == 403


def test_stale_running_job_requires_explicit_retry(paired, service):
    client, sessions, _, run, _ = paired
    settings = enable(service)
    url = f"/v1/replay/runs/{run['id']}/ai-review"
    client.post(url, json={"consent": True})
    with sessions.begin() as db:
        record = db.scalar(select(AIReview).where(AIReview.run_id == run["id"]))
        record.status, record.started_at = "generating", now() - timedelta(minutes=3)
    ai_review.process_next(sessions, settings)
    assert client.get(url).json()["status"] == "failed"
    assert client.get(url).json()["attempts"] == 1


@pytest.mark.parametrize("mutation", ["number", "duplicate", "unknown_key"])
def test_narrative_validation_rejects_ungrounded_output(mutation):
    value = output({})["content"]
    if mutation == "number":
        value["observations"][0]["interpretation"] = "세부 수익률은 99%입니다."
    elif mutation == "duplicate":
        value["observations"] *= 2
    else:
        value["buy_now"] = True
    with pytest.raises(Exception):
        ai_review.validate_narrative(value, {"facts": [{"fact_id": "plan"}]})


def test_daily_attempt_budget_is_shared_between_runs(paired, service):
    client, sessions, _, first, second = paired
    enable(service)
    url = f"/v1/replay/runs/{first['id']}/ai-review"
    assert client.post(url, json={"consent": True}).status_code == 200
    with sessions.begin() as db:
        row = db.scalar(select(AIReview).where(AIReview.run_id == first["id"]))
        row.data = {**row.data, "attempt_times": [now().isoformat()] * 5}
    other = f"/v1/replay/runs/{second['id']}/ai-review"
    assert client.post(other, json={"consent": True}).status_code == 429
    # Cached pending requests do not consume another attempt.
    assert client.post(url, json={"consent": True}).json()["attempts"] == 1
