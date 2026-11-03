"""Research integrity checks, not just screen/API response shape assertions."""

import copy
import csv
import io
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import Holding, Order, Quote, ReplayCase, ReplayRun, User
from app.services import replay


def key():
    return str(uuid4())


@pytest.fixture
def setup(service):
    client, sessions, uid, _ = service
    response = client.post("/v1/replay/practice")
    assert response.status_code == 200, response.text
    case = response.json()
    response = client.post(
        f"/v1/replay/cases/{case['id']}/runs",
        json={
            "request_id": key(),
            "pilot_enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    return client, sessions, uid, case, response.json()


def act(client, run, action, **extra):
    response = client.post(
        f"/v1/replay/runs/{run['id']}/actions",
        json={
            "request_id": key(),
            "revision": run["revision"],
            "action": action,
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def order(client, run, side="buy", qty=1, price=None):
    price = price or run["visible_bars"][-1]["close_won"]
    draft = dict(side=side, quantity=qty, limit_price_won=price)
    run = act(client, run, "check", **draft)
    check = run["action_result"]
    assert check["allowed"], check
    run = act(client, run, "presented", check_id=check["check_id"])
    return act(
        client,
        run,
        "submit",
        **draft,
        check_id=check["check_id"],
        warning_acknowledged=True,
        high_risk_acknowledged=True,
        reason="실험 사전 판단",
    )


def test_model_prefix_isolation_and_no_future_disclosure(setup):
    client, sessions, uid, c, run = setup
    assert c["data_kind"] == "synthetic"
    assert c["model"]["quality_gate_passed"]
    assert run["prediction"]["status"] == "available"
    assert "rows" not in c and "artifact" not in c
    assert len(run["visible_bars"]) == 35
    assert "shadow" not in str(run)
    with sessions.begin() as db:
        case = db.get(ReplayCase, c["id"])
        prefix = case.rows[: case.config["start"]]
        assert case.artifact["csv_sha256"] == replay.digest(prefix)
        assert replay.stamp(case.artifact["data_end"]) <= replay.stamp(case.config["replay_from"])
        first = replay.prediction(case, db.get(ReplayRun, run["id"]).state)
        changed = copy.deepcopy(case.rows)
        for row in changed[case.config["start"] + 1 :]:
            row["close_won"] *= 2
        case.rows = changed
        # Future changes must not affect today's inference or returned chart.
        assert replay.prediction(case, db.get(ReplayRun, run["id"]).state) == first
        assert (
            replay.view(case, db.get(ReplayRun, run["id"]))["visible_bars"] == run["visible_bars"]
        )
    assert client.get(f"/v1/replay/runs/{run['id']}/export").status_code == 409


def test_randomized_condition_order_is_server_assigned_and_reproducible(setup):
    client, _, _, case, _ = setup
    url = f"/v1/replay/cases/{case['id']}/runs"
    payload = {"request_id": key(), "randomize_order": True}
    response = client.post(url, json=payload)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["allocation_method"] == "server_randomized"
    assert first["condition_order"] in (["ON", "OFF"], ["OFF", "ON"])
    assert first["pilot_enabled"] == (first["condition_order"][0] == "ON")
    assert first["sequence"] == 1 and first["allocation_at"]
    assert client.post(url, json=payload).json() == first

    first = act(client, first, "finish")
    second = client.post(
        url,
        json={
            "request_id": key(),
            "pilot_enabled": not first["pilot_enabled"],
            "paired_run_id": first["id"],
        },
    )
    assert second.status_code == 200, second.text
    second = second.json()
    assert second["allocation_method"] == "server_randomized"
    assert second["condition_order"] == first["condition_order"]
    assert second["pair_id"] == first["pair_id"] and second["sequence"] == 2
    second = act(client, second, "finish")
    exported = client.get(f"/v1/replay/runs/{second['id']}/export").json()
    assert exported["evidence"]["state"]["condition_order"] == first["condition_order"]
    assert "allocation_method" in exported["csv"]
    assert "condition_order" in exported["csv"]


@pytest.mark.parametrize(
    "payload",
    [
        {"request_id": key(), "randomize_order": True, "pilot_enabled": True},
        {"request_id": key(), "randomize_order": True, "paired_run_id": key()},
        {"request_id": key(), "randomize_order": False},
    ],
)
def test_randomized_order_rejects_ambiguous_allocations(setup, payload):
    client, _, _, case, _ = setup
    response = client.post(f"/v1/replay/cases/{case['id']}/runs", json=payload)
    assert response.status_code == 422


def test_next_open_fill_idempotency_balance_isolation(setup):
    client, sessions, uid, c, run = setup
    with sessions.begin() as db:
        cash = db.get(User, uid).cash_won
        holdings = [
            (h.symbol, h.quantity)
            for h in db.scalars(select(Holding).where(Holding.user_id == uid))
        ]
        quotes = [(q.symbol, q.price_won, q.as_of) for q in db.scalars(select(Quote))]
        next_open = db.get(ReplayCase, c["id"]).rows[run["cursor"] + 1]["open_won"]
    run = order(client, run, price=next_open + 100)
    assert run["orders"][-1]["status"] == "accepted"
    assert run["quantity"] == 0
    assert run["available_cash_won"] < run["cash_won"]
    body = dict(request_id=key(), revision=run["revision"], action="advance")
    path = f"/v1/replay/runs/{run['id']}/actions"
    first = client.post(path, json=body)
    assert first.status_code == 200, first.text
    repeated = client.post(path, json=body)
    assert repeated.json() == first.json()
    run = first.json()
    assert run["orders"][-1]["fill_price"] == next_open
    assert run["quantity"] == 1
    assert run["cash_won"] == 10_000_000 - next_open - replay.fee(next_open)
    assert client.post(path, json={**body, "quantity": 2}).status_code == 409
    assert client.post(path, json={**body, "request_id": key()}).status_code == 409
    with sessions.begin() as db:
        assert db.get(User, uid).cash_won == cash
        assert [
            (h.symbol, h.quantity)
            for h in db.scalars(select(Holding).where(Holding.user_id == uid))
        ] == holdings
        assert [(q.symbol, q.price_won, q.as_of) for q in db.scalars(select(Quote))] == quotes
        assert not db.scalars(select(Order).where(Order.user_id == uid)).all()


def test_off_shadow_not_exposed_and_paired_export(setup):
    client, sessions, uid, c, run = setup
    for _ in range(5):
        run = act(client, run, "advance")
    run = act(client, run, "check", limit_price_won=run["visible_bars"][-1]["close_won"])
    check = run["action_result"]
    assert check["analysis"]["behavior"]["score"] == 30
    run = act(client, run, "presented", check_id=check["check_id"])
    run = act(client, run, "defer", check_id=check["check_id"])
    run = act(client, run, "finish")
    assert run["summary"]["warned_deferrals"] == 1
    assert run["summary"]["plan_compliance_rate"] is None
    off = client.post(
        f"/v1/replay/cases/{c['id']}/runs",
        json={
            "request_id": key(),
            "pilot_enabled": False,
            "paired_run_id": run["id"],
        },
    ).json()
    assert off["pair_id"] == run["pair_id"] and off["sequence"] == 2
    assert off["comparison_key"] == run["comparison_key"]
    for _ in range(5):
        off = act(client, off, "advance")
    off = order(client, off)
    assert off["orders"][0]["analysis"]["behavior"]["score"] == 0
    assert off["orders"][0]["analysis"]["behavior"]["items"] == []
    assert "shadow" not in str(off)
    off = act(client, off, "finish")
    assert off["summary"]["warnings_presented"] == 0
    assert off["summary"]["rule_qualified_submissions"] == 1
    assert off["orders"][0]["status"] == "cancelled"
    report = client.get(f"/v1/replay/runs/{off['id']}/export").json()
    row = list(csv.DictReader(io.StringIO(report["csv"])))[0]
    assert row["shadow_score"] == "30" and row["warning_shown"] == "False"
    assert report["evidence"]["model"]["version"] == c["model"]["version"]
    assert replay.digest(report["evidence"]["case_rows"]) == c["data_sha256"]


def test_risk_enforced_off_and_check_cannot_be_reused(setup):
    client, sessions, uid, c, initial = setup
    run = client.post(
        f"/v1/replay/cases/{c['id']}/runs", json={"request_id": key(), "pilot_enabled": False}
    ).json()
    run = act(client, run, "check", side="sell", quantity=1, limit_price_won=70000)
    assert not run["action_result"]["allowed"]
    run = act(client, run, "check", quantity=100, limit_price_won=70000)
    assert not run["action_result"]["allowed"]
    run = order(client, run, price=75000)
    run = act(client, run, "check", limit_price_won=75000)
    assert not run["action_result"]["allowed"]
    assert any("쿨다운" in x for x in run["action_result"]["messages"])
    run = act(client, run, "advance")
    run = act(client, run, "check", limit_price_won=75000)
    check = run["action_result"]
    assert check["allowed"]
    run = act(client, run, "advance")
    result = client.post(
        f"/v1/replay/runs/{run['id']}/actions",
        json={
            "request_id": key(),
            "revision": run["revision"],
            "action": "submit",
            "check_id": check["check_id"],
            "limit_price_won": 75000,
        },
    )
    assert result.status_code == 409


def test_cancel_reservations_plan_snapshot_and_start_retry(setup):
    client, sessions, uid, c, _ = setup
    payload = dict(
        request_id=key(),
        pilot_enabled=True,
        plan=dict(
            entry_min_won=60000, entry_max_won=80000, max_amount_won=1000000, split_order=True
        ),
    )
    url = f"/v1/replay/cases/{c['id']}/runs"
    run = client.post(url, json=payload).json()
    assert client.post(url, json=payload).json()["id"] == run["id"]
    assert client.post(url, json={**payload, "pilot_enabled": False}).status_code == 409
    run = order(client, run, price=60000)
    assert run["available_cash_won"] < run["cash_won"]
    run = act(client, run, "cancel", order_id=run["orders"][0]["id"])
    assert run["available_cash_won"] == run["cash_won"]
    run = act(client, run, "advance")
    assert run["quantity"] == 0
    for _ in range(4):
        run = act(client, run, "advance")
    run = act(client, run, "check", limit_price_won=run["visible_bars"][-1]["close_won"])
    assert any(
        i["code"] == "fomo" and i["status"] == "exempt"
        for i in run["action_result"]["analysis"]["behavior"]["items"]
    )


def test_private_access_dataset_snapshot_and_no_retraining(setup):
    client, sessions, uid, c, run = setup
    with sessions.begin() as db:
        source = db.get(ReplayCase, c["id"])
        rows = source.rows
        # CSV storage can be deleted later without losing the research case snapshot.
        from app.models import Dataset

        ds = Dataset(
            user_id=uid,
            name="historical upload",
            symbol="005930",
            provider="user-test",
            data_kind="historical",
            rows=rows,
            summary={"sha256": replay.digest(rows)},
        )
        db.add(ds)
        db.flush()
        dsid = ds.id
    response = client.post(
        "/v1/replay/cases",
        json=dict(
            dataset_id=dsid, name="case", replay_from=c["replay_from"], event_key="selloff_2024"
        ),
    )
    assert response.status_code == 200, response.text
    cid = response.json()["id"]
    assert client.delete(f"/v1/datasets/{dsid}").status_code in (200, 204)
    result = client.post(
        f"/v1/replay/cases/{cid}/runs", json=dict(request_id=key(), pilot_enabled=True)
    )
    assert result.status_code == 200, result.text
    assert result.json()["prediction"]["status"] == "unavailable"
    assert client.post(f"/v1/replay/cases/{cid}/train").status_code == 409
    client.post(
        "/v1/auth/signup",
        json={
            "email": "other@example.com",
            "password": "other-password-123",
            "password_confirmation": "other-password-123",
        },
    )
    login = client.post(
        "/v1/auth/login",
        json={
            "email": "other@example.com",
            "password": "other-password-123",
            "password_confirmation": "other-password-123",
        },
    )
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    assert client.get(f"/v1/replay/runs/{run['id']}").status_code == 404
    assert client.post(f"/v1/replay/cases/{c['id']}/train").status_code == 404
    assert client.get("/v1/replay").json()["runs"] == []


def test_wall_expiry_and_confirmations(setup):
    client, sessions, uid, c, run = setup
    for _ in range(5):
        run = act(client, run, "advance")
    price = run["visible_bars"][-1]["close_won"]
    run = act(client, run, "check", limit_price_won=price)
    check = run["action_result"]
    path = f"/v1/replay/runs/{run['id']}/actions"
    submit = dict(
        request_id=key(),
        revision=run["revision"],
        action="submit",
        check_id=check["check_id"],
        limit_price_won=price,
    )
    assert client.post(path, json=submit).status_code == 422
    with sessions.begin() as db:
        r = db.get(ReplayRun, run["id"])
        s = copy.deepcopy(r.state)
        s["checks"][-1]["expires_at"] = (replay.now() - timedelta(seconds=1)).isoformat()
        r.state = s
    assert client.post(path, json=submit).status_code == 409


def test_virtual_panic_sell_uses_fee_inclusive_cost_and_sell_plan(setup):
    client, sessions, uid, c, _ = setup
    response = client.post(
        f"/v1/replay/cases/{c['id']}/runs",
        json=dict(
            request_id=key(),
            pilot_enabled=True,
            plan=dict(
                side="sell",
                entry_min_won=70000,
                entry_max_won=80000,
                max_amount_won=1000000,
                stop_loss_won=70000,
            ),
        ),
    )
    run = response.json()
    run = order(client, run, price=75000)
    # A sell-only plan is not incorrectly applied as a violated buy plan.
    assert run["orders"][0]["analysis"]["context"]["plan_status"] == "unregistered"
    for _ in range(16):
        run = act(client, run, "advance")
    run = act(
        client, run, "check", side="sell", limit_price_won=run["visible_bars"][-1]["close_won"]
    )
    a = run["action_result"]["analysis"]
    assert float(a["context"]["position_return_percent"]) < 0
    assert float(a["behavior"]["change_10m_percent"]) < -3
    assert any(i["code"] == "panic" and i["status"] == "exempt" for i in a["behavior"]["items"])


def test_prediction_abstains_on_gap_failed_validation_and_late_session(setup):
    client, sessions, uid, c, run = setup
    with sessions.begin() as db:
        case = db.get(ReplayCase, c["id"])
        state = copy.deepcopy(db.get(ReplayRun, run["id"]).state)
        state["cursor"] = len(case.rows) - 1
        assert "1시간 미만" in replay.prediction(case, state)["message"]
        state["cursor"] = 78  # First bar of another session, too few continuous bars.
        # A pre-training bar must also never receive an inference from a future model.
        assert replay.prediction(case, state)["status"] == "unavailable"
        state["cursor"] = run["cursor"]
        artifact = copy.deepcopy(case.artifact)
        artifact["quality_gate_passed"] = False
        case.artifact = artifact
        assert "검증 기준 미달" in replay.prediction(case, state)["message"]


def test_frozen_prediction_review_is_finished_only_and_exported(setup):
    client, sessions, _, case, run = setup
    assert run["prediction_review"] is None
    for _ in range(2):
        run = act(
            client,
            run,
            "check",
            side="buy",
            quantity=1,
            limit_price_won=run["visible_bars"][-1]["close_won"],
        )
    snapshot = copy.deepcopy(run["action_result"]["analysis"]["prediction"])
    for _ in range(12):
        run = act(client, run, "advance")
    assert run["prediction_review"] is None
    run = act(client, run, "finish")
    review = run["prediction_review"]
    assert review["summary"]["unique_predictions"] == 1
    assert review["summary"]["resolved"] == 1
    observation = review["observations"][0]
    assert observation["prediction"] == snapshot
    assert len(observation["check_ids"]) == 2
    assert observation["outcome"]["target_price_won"] == run["visible_bars"][-1]["close_won"]
    export = client.get(f"/v1/replay/runs/{run['id']}/export").json()
    assert export["evidence"]["prediction_review"] == review
    rows = list(csv.DictReader(io.StringIO(export["csv"])))
    assert len(rows) == 2
    assert all(r["prediction_outcome_status"] == "resolved" for r in rows)
    assert all(r["prediction_as_of"] == snapshot["as_of"] for r in rows)
    # A later model change must not change the saved forecast being reviewed.
    with sessions.begin() as db:
        c = db.get(ReplayCase, case["id"])
        c.artifact = None
    assert client.get(f"/v1/replay/runs/{run['id']}").json()["prediction_review"] == review


def test_pair_has_exactly_two_runs_and_retries_remain_idempotent(setup):
    client, _, _, case, first = setup
    first = act(client, first, "finish")
    url = f"/v1/replay/cases/{case['id']}/runs"
    body = dict(request_id=key(), pilot_enabled=False, paired_run_id=first["id"])
    second = client.post(url, json=body)
    assert second.status_code == 200
    assert client.post(url, json=body).json() == second.json()
    duplicate = client.post(url, json={**body, "request_id": key()})
    assert duplicate.status_code == 409
    second = act(client, second.json(), "finish")
    third = client.post(
        url, json=dict(request_id=key(), pilot_enabled=True, paired_run_id=second["id"])
    )
    assert third.status_code == 409


def test_saved_rule_version_survives_deployment_and_pair_rejects_policy_change(setup, monkeypatch):
    client, _, _, case, run = setup
    run = act(client, run, "check", limit_price_won=run["visible_bars"][-1]["close_won"])
    version = run["action_result"]["analysis"]["version"]
    monkeypatch.setattr(replay.risk, "VERSION", "future-policy")
    denied = client.post(
        f"/v1/replay/runs/{run['id']}/actions",
        json=dict(
            request_id=key(), revision=run["revision"], action="check", limit_price_won=70000
        ),
    )
    assert denied.status_code == 409
    run = act(client, run, "finish")
    exported = client.get(f"/v1/replay/runs/{run['id']}/export").json()
    row = list(csv.DictReader(io.StringIO(exported["csv"])))[0]
    assert row["rule_version"] == version
    result = client.post(
        f"/v1/replay/cases/{case['id']}/runs",
        json=dict(request_id=key(), pilot_enabled=False, paired_run_id=run["id"]),
    )
    assert result.status_code == 409


def test_pair_rejects_changed_execution_config(setup, monkeypatch):
    client, _, _, case, run = setup
    run = act(client, run, "finish")
    monkeypatch.setattr(replay, "CONFIG", {**replay.CONFIG, "fee_rate": "0.02"})
    result = client.post(
        f"/v1/replay/cases/{case['id']}/runs",
        json=dict(request_id=key(), pilot_enabled=False, paired_run_id=run["id"]),
    )
    assert result.status_code == 409


def test_deferred_reason_is_preserved_without_creating_order_and_csv_is_safe(setup):
    client, _, _, _, run = setup
    run = act(client, run, "check", limit_price_won=run["visible_bars"][-1]["close_won"])
    check_id = run["action_result"]["check_id"]
    run = act(client, run, "presented", check_id=check_id)
    body = dict(
        request_id=key(),
        revision=run["revision"],
        action="defer",
        check_id=check_id,
        reason="  =진입 조건을 재확인  ",
    )
    url = f"/v1/replay/runs/{run['id']}/actions"
    response = client.post(url, json=body)
    assert response.status_code == 200
    assert client.post(url, json=body).json() == response.json()
    run = response.json()
    assert run["decisions"] is None and run["orders"] == []
    run = act(client, run, "finish")
    assert run["decisions"][0]["reason"] == "=진입 조건을 재확인"
    exported = client.get(f"/v1/replay/runs/{run['id']}/export").json()
    row = list(csv.DictReader(io.StringIO(exported["csv"])))[0]
    assert row["reason"] == "'=진입 조건을 재확인"
    assert exported["evidence"]["state"]["checks"][0]["decision_reason"] == "=진입 조건을 재확인"
    assert row["order_id"] == ""


def test_blank_deferral_and_close_do_not_invent_reason(setup):
    client, _, _, _, run = setup
    for action in ("defer", "close"):
        run = act(client, run, "check", limit_price_won=run["visible_bars"][-1]["close_won"])
        check_id = run["action_result"]["check_id"]
        run = act(
            client,
            run,
            action,
            check_id=check_id,
            reason="닫기에서는 저장 안 함" if action == "close" else "",
        )
    run = act(client, run, "finish")
    assert all(d["reason"] == "" for d in run["decisions"])
    assert run["summary"]["explicit_deferrals"] == 1
