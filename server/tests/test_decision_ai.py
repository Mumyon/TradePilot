"""Verify the treatment boundary and both decision stages."""

import json
from datetime import timedelta
from types import SimpleNamespace

from test_api import checked
from test_replay import act, key

from app.llm import chatgpt
from app.models import now
from app.services import ai_review, decision_ai, replay


def test_replay_ai_pair_isolated_with_both_exposures_and_off_control(service, monkeypatch):
    client, sessions, uid, settings = service
    settings.ai_review_enabled = True
    settings.ai_review_local_only = False
    monkeypatch.setattr(chatgpt, "connection", lambda *_: {"model": "test-model"})
    calls = []

    def generate(*args, **kwargs):
        assert not kwargs.get("web_search", False)
        payload = args[4]
        calls.append(payload)
        assert uid not in json.dumps(payload)
        return dict(
            content=dict(
                summary="공개 봉을 확인했습니다.", risk="변동성", next_check="지정가 확인"
            ),
            response_model="test-model",
        )

    monkeypatch.setattr(chatgpt, "generate", generate)
    case = client.post("/v1/replay/practice").json()
    start = f"/v1/replay/cases/{case['id']}/runs"
    run = client.post(
        start,
        json=dict(
            request_id=key(),
            experiment="ai_feedback",
            pilot_enabled=True,
        ),
    ).json()
    base = f"/v1/replay/runs/{run['id']}"
    market = base + "/decision-ai/market"
    draft = dict(side="buy", quantity=1, limit_price_won=run["visible_bars"][-1]["close_won"])
    run = act(client, run, "check", **draft)
    check = run["action_result"]
    assert check["allowed"] and not check["analysis"]["behavior"]["enabled"]
    check_id = check["check_id"]
    order = base + f"/decision-ai/order?check_id={check_id}"
    display = base + f"/order-display/{check_id}"
    assert client.put(display).status_code == 409
    assert client.post(order, json={"consent": True}).status_code == 409
    assert client.put(market).status_code == 409
    assert client.post(market, json={"consent": True}).json()["status"] == "pending"
    assert client.post(market, json={"consent": True}).json()["attempts"] == 1
    ai_review.process_next(sessions, settings)
    assert client.get(market).json()["result"]["kind"] == "decision_feedback"
    assert client.put(market).status_code == 200
    assert client.put(market).status_code == 200
    assert calls[0]["stage"] == "market"
    visible = run["visible_bars"][-35:]
    assert [x["close_won"] for x in calls[0]["visible_bars"]] == [x["close_won"] for x in visible]
    assert all("opened_at" not in x for x in calls[0]["visible_bars"])

    assert client.post(order, json={"consent": True}).json()["status"] == "pending"
    blocked = client.post(
        base + "/actions",
        json=dict(
            request_id=key(),
            revision=run["revision"],
            action="submit",
            check_id=check_id,
            **draft,
        ),
    )
    assert blocked.status_code == 409
    ai_review.process_next(sessions, settings)
    shown_at = now() + timedelta(seconds=12)
    with monkeypatch.context() as clock:
        clock.setattr(replay, "now", lambda: shown_at)
        displayed = client.put(display)
        assert displayed.status_code == 200
        assert client.put(display).json() == displayed.json()
    assert client.put(order).status_code == 200
    assert calls[1]["stage"] == "order" and calls[1]["draft"]["side"] == "buy"
    assert calls[1]["prior_market_analysis"]
    run = act(client, run, "presented", check_id=check_id)
    with monkeypatch.context() as clock:
        clock.setattr(replay, "now", lambda: shown_at + timedelta(seconds=3))
        run = act(client, run, "submit", check_id=check_id, **draft)
    run = act(client, run, "finish")
    assert run["summary"]["market_feedback_seen"] == 1
    assert run["summary"]["order_feedback_seen"] == 1
    assert run["summary"]["warnings_presented"] == 0
    assert run["summary"]["full_horizon"] is False
    assert run["summary"]["ai_wait_seconds_mean"] >= 12
    assert run["summary"]["post_display_seconds_mean"] == 3
    report = client.get(base + "/export").json()
    assert len(report["evidence"]["decision_ai"]) == 2
    assert "ai_order_seen_at" in report["csv"]
    assert report["evidence"]["order_measurements"][0]["post_display_seconds"] == 3

    off = client.post(
        start,
        json=dict(
            request_id=key(),
            experiment="ai_feedback",
            pilot_enabled=False,
            paired_run_id=run["id"],
        ),
    ).json()
    assert off["comparison_key"] == run["comparison_key"]
    assert off["config"] == run["config"]
    off_market = f"/v1/replay/runs/{off['id']}/decision-ai/market"
    assert client.post(off_market, json={"consent": True}).status_code == 409
    off = act(client, off, "check", **draft)
    off_check = off["action_result"]
    assert not off_check["analysis"]["behavior"]["enabled"]
    off = act(client, off, "presented", check_id=off_check["check_id"])
    assert (
        client.put(f"/v1/replay/runs/{off['id']}/order-display/{off_check['check_id']}").status_code
        == 200
    )
    off = act(client, off, "submit", check_id=off_check["check_id"], **draft)
    off = act(client, off, "finish")
    assert off["summary"]["order_feedback_seen"] == 0
    assert off["summary"]["ai_wait_timed_count"] == 0
    assert off["summary"]["post_display_timed_count"] == 1
    assert off["summary"]["accepted_orders"] == run["summary"]["accepted_orders"] == 1
    assert len(calls) == 2


def test_live_order_reuses_recent_chart_analysis(service, monkeypatch):
    client, sessions, _, settings = service
    settings.ai_review_enabled = True
    settings.ai_review_local_only = False
    monkeypatch.setattr(chatgpt, "connection", lambda *_: {"model": "test-model"})
    calls = []

    def generate(*args, **kwargs):
        calls.append(args[4])
        if kwargs.get("web_search"):
            return dict(
                content="PILOT_SIGNAL=관망\n\n시장 보고서",
                search=dict(used=True, completed_calls=1, sources=[]),
            )
        return dict(
            content=dict(
                judgment="관망", summary="지정가 검토", risk="변동성", next_check="호가 확인"
            )
        )

    monkeypatch.setattr(chatgpt, "generate", generate)
    chart = "/v1/market/005930/ai-analysis"
    assert client.get(chart).json()["status"] == "ready"
    assert not calls
    automatic = {"consent": True, "automatic": True}
    assert client.post(chart, json=automatic).json()["status"] == "pending"
    assert client.post(chart, json=automatic).json()["attempts"] == 1
    ai_review.process_next(sessions, settings)
    analysis = client.get(chart).json()
    assert analysis["result"] == {"kind": "quant_web", "body": "시장 보고서", "judgment": "관망"}
    assert analysis["prompt_version"] == decision_ai.MARKET_VERSION
    assert calls[0]["recent_candles"] is None  # Synthetic demo bars stay out of the request.
    assert client.post(chart, json=automatic).json()["status"] == "available"
    assert len(calls) == 1
    check = checked(client)
    order = f"/v1/orders/check/{check['check_id']}/ai-feedback"
    assert client.post(order, json={"consent": True}).json()["status"] == "pending"
    ai_review.process_next(sessions, settings)
    assert client.get(order).json()["result"]["kind"] == "decision_feedback"
    assert client.get(order).json()["result"]["judgment"] == "관망"
    assert calls[1]["prior_market_analysis"]["report"] == "시장 보고서"
    assert calls[1]["order_side"] == "buy"
    assert calls[1]["limit_price_won"] > 0


def test_chart_automatic_request_does_not_retry_failed_analysis(service, monkeypatch):
    client, sessions, _, settings = service
    settings.ai_review_enabled = True
    settings.ai_review_local_only = False
    monkeypatch.setattr(chatgpt, "connection", lambda *_: {"model": "test-model"})

    def failed(*args, **kwargs):
        raise chatgpt.ReviewError("timeout")

    monkeypatch.setattr(chatgpt, "generate", failed)
    chart = "/v1/market/005930/ai-analysis"
    automatic = {"consent": True, "automatic": True}
    assert client.post(chart, json=automatic).json()["status"] == "pending"
    ai_review.process_next(sessions, settings)
    result = client.post(chart, json=automatic).json()
    assert (result["status"], result["attempts"]) == ("failed", 1)
    retry = client.post(chart, json={"consent": True}).json()
    assert (retry["status"], retry["attempts"]) == ("pending", 2)


def test_chart_uses_actual_five_minute_summary_when_search_fails(service, monkeypatch):
    client, sessions, _, settings = service
    settings.ai_review_enabled = True
    settings.ai_review_local_only = False
    summary = {"source": "toss_kr", "count": 12}
    monkeypatch.setattr(decision_ai, "recent_market_candles", lambda *args: summary)
    monkeypatch.setattr(chatgpt, "connection", lambda *_: {"model": "test-model"})

    def generate(*args, **kwargs):
        if kwargs.get("web_search"):
            raise chatgpt.ReviewError("provider_failed")
        assert kwargs["plain_text"]
        assert args[4]["recent_candles"] == summary
        assert "research_window" not in args[4]
        return {"content": "**PILOT_SIGNAL=보류**\n관측 자료 기준 요약"}

    monkeypatch.setattr(chatgpt, "generate", generate)
    path = "/v1/market/005930/ai-analysis"
    assert client.post(path, json={"consent": True}).json()["status"] == "pending"
    ai_review.process_next(sessions, settings)
    result = client.get(path).json()
    assert result["status"] == "available"
    assert result["result"] == {
        "kind": "market_snapshot",
        "judgment": "보류",
        "body": "관측 자료 기준 요약",
    }


def test_market_snapshot_uses_only_contiguous_completed_provider_candles():
    at = now()

    def bar(minutes_ago, **extra):
        return {
            "opened_at": at - timedelta(minutes=minutes_ago),
            "open_won": 100,
            "close_won": 104,
            "low_won": 99,
            "high_won": 110,
            "volume": 50,
            "source": "toss_kr",
            "complete": True,
            **extra,
        }

    rows = [
        bar(2),
        bar(5, source="demo"),
        bar(5, complete=False),
        bar(10),
        bar(15, open_won=80, low_won=75),
        bar(25, volume=500),
    ]
    settings = SimpleNamespace(market_data_mode="toss")
    provider = SimpleNamespace(get_feedback_candles=lambda _: rows)
    snapshot = decision_ai.recent_market_candles(None, "005930", settings, at, provider)
    assert snapshot == {
        "source": "toss_kr",
        "interval": "5m",
        "count": 2,
        "started_at": (at - timedelta(minutes=15)).isoformat(),
        "closed_at": (at - timedelta(minutes=5)).isoformat(),
        "stale": False,
        "last_close_won": 104,
        "high_won": 110,
        "low_won": 75,
        "volume": 100,
        "open_to_close_pct": 30,
        "return_15m_pct": None,
        "return_60m_pct": None,
        "volume_change_15m_pct": None,
    }
    rows[:] = [bar(i * 5, volume=100 if i <= 3 else 50) for i in range(1, 13)]
    snapshot = decision_ai.recent_market_candles(None, "005930", settings, at, provider)
    assert snapshot["return_15m_pct"] == snapshot["return_60m_pct"] == 4
    assert snapshot["volume_change_15m_pct"] == 100


def test_order_feedback_outcome_is_frozen_when_user_leaves(service, monkeypatch):
    client, sessions, _, settings = service
    settings.ai_review_enabled = True
    settings.ai_review_local_only = False
    monkeypatch.setattr(chatgpt, "connection", lambda *_: {"model": "test-model"})

    def generate(*args, **kwargs):
        if args[4]["stage"] == "order":
            raise chatgpt.ReviewError("timeout")
        return dict(content=dict(summary="시세", risk="위험", next_check="확인"))

    monkeypatch.setattr(chatgpt, "generate", generate)
    case = client.post("/v1/replay/practice").json()
    run = client.post(
        f"/v1/replay/cases/{case['id']}/runs",
        json=dict(request_id=key(), experiment="ai_feedback", pilot_enabled=True),
    ).json()
    base = f"/v1/replay/runs/{run['id']}"
    assert client.post(base + "/decision-ai/market", json={"consent": True}).status_code == 200
    ai_review.process_next(sessions, settings)
    assert client.put(base + "/decision-ai/market").status_code == 200

    for expected in ("failed", "pending", "not_requested"):
        run = act(client, run, "check", limit_price_won=run["visible_bars"][-1]["close_won"])
        check_id = run["action_result"]["check_id"]
        if expected != "not_requested":
            path = base + f"/decision-ai/order?check_id={check_id}"
            assert client.post(path, json={"consent": True}).status_code == 200
        if expected == "failed":
            ai_review.process_next(sessions, settings)
        run = act(client, run, "close", check_id=check_id)
        if expected == "pending":
            # The job becomes stale afterward. The research outcome remains "pending".
            ai_review.process_next(sessions, settings)

    run = act(client, run, "finish")
    stats = run["summary"]
    assert stats["advice_failed_checks"] == stats["advice_waiting_at_end_checks"] == 1
    assert stats["advice_not_requested_checks"] == 1
    assert stats["post_display_timed_count"] == 0
    evidence = client.get(base + "/export").json()["evidence"]
    assert [row["ai_order_status"] for row in evidence["order_measurements"]] == [
        "failed",
        "pending",
        "not_requested",
    ]
