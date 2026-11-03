import csv
import io
from datetime import timedelta

from test_risk import check, plan, quotes, send

from app.models import OrderCheck, User, now
from app.schemas import Draft
from app.services import orders


def presented(client, result):
    response = client.post(f"/v1/orders/check/{result['check_id']}/presented")
    assert response.status_code == 200, response.text
    return response.json()["presented_at"]


def report(client):
    response = client.get("/v1/feedback")
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_and_off_do_not_invent_prevention_or_zero_risk(service):
    client = quotes(service)
    empty = report(client)
    assert empty["groups"]["on"]["plan_compliance"] is None
    assert empty["compliance_difference_pp"] is None
    body, result = check(client, pilot_enabled=False)
    presented(client, result)
    send(client, body, result)
    data = report(client)
    assert data["groups"]["off"]["checks"] == 1
    assert data["groups"]["on"]["checks"] == 0
    assert data["items"][0]["score"] is None
    assert data["items"][0]["warnings"] == []
    assert all(r["defer_rate"] is None for r in data["warning_types"])


def test_explicit_defer_is_once_and_exposure_timestamp_is_immutable(service):
    client = quotes(service)
    _, result = check(client)
    first = presented(client, result)
    assert presented(client, result) == first
    url = f"/v1/orders/check/{result['check_id']}/dismiss"
    assert client.post(url).json()["decision"] == "dismissed"
    data = report(client)
    decided = data["items"][0]["decided_at"]
    client.post(url)
    assert report(client)["items"][0]["decided_at"] == decided
    assert presented(client, result) == first
    fomo = data["warning_types"][0]
    assert fomo["presented"] == fomo["voluntary_resolved"] == 1
    assert fomo["defer_rate"] == 1
    assert data["items"][0]["decision_seconds"] >= 0


def test_outcomes_distinguish_rejection_cancellation_fill_and_pending(service):
    from test_portfolio import settle

    client = quotes(service)
    body, result = check(client)
    presented(client, result)
    rejected = send(client, body, result, key="no-ack").json()
    assert rejected["status"] == "rejected"
    assert report(client)["warning_types"][0]["defer_rate"] is None
    body, result = check(client)
    presented(client, result)
    arguments = dict(warning_acknowledged=True, trade_reason="계획 재확인")
    receipt = send(client, body, result, key="cancel", **arguments).json()
    assert send(client, body, result, key="cancel", **arguments).json() == receipt
    client.post(f"/v1/orders/{receipt['order_id']}/cancel")
    body, result = check(client)
    presented(client, result)
    send(client, body, result, key="fill", **arguments)
    settle(service, 103000)
    _, result = check(client)
    presented(client, result)
    data = report(client)
    fomo = data["warning_types"][0]
    assert fomo["outcomes"] == {"rejected": 1, "cancelled": 1, "filled": 1, "pending": 1}
    assert fomo["voluntary_resolved"] == 2
    assert fomo["defer_rate"] == 0
    assert data["total_checks"] == 4


def test_never_shown_blocked_or_expired_not_counted_as_voluntary_defer(service):
    client = quotes(service)
    _, result = check(client)
    client.post(f"/v1/orders/check/{result['check_id']}/dismiss")
    _, expired = check(client)
    presented(client, expired)
    _, sessions, uid, _ = service
    with sessions.begin() as db:
        c = db.get(OrderCheck, expired["check_id"])
        c.expires_at = now() - timedelta(seconds=1)
        db.get(User, uid).trading_paused = True
    client.post(f"/v1/orders/check/{expired['check_id']}/dismiss")
    _, blocked = check(client)
    assert not blocked["allowed"]
    assert client.post(f"/v1/orders/check/{blocked['check_id']}/presented").status_code == 409
    data = report(client)
    assert data["warning_types"][0]["defer_rate"] is None
    assert {r["outcome"] for r in data["items"]} == {"dismissed", "expired", "blocked"}


def test_on_off_plan_compliance_uses_filled_evaluable_orders(service):
    from test_portfolio import settle

    client = quotes(service, current=100000)
    good = plan(service)
    bad = plan(service, max_amount_won=1)
    for i, (enabled, chosen) in enumerate([(True, good), (False, bad), (True, None)]):
        body, result = check(client, pilot_enabled=enabled, plan_id=chosen)
        presented(client, result)
        assert send(client, body, result, key=f"plan-{i}").json()["status"] == "accepted"
        settle(service, 100000)
    data = report(client)
    assert data["groups"]["on"]["plan_compliance"] == 1
    assert data["groups"]["on"]["plan_unregistered"] == 1
    assert data["groups"]["on"]["plan_evaluated"] == 1
    assert data["groups"]["off"]["plan_compliance"] == 0
    assert data["compliance_difference_pp"] == 100


def test_automation_and_legacy_excluded_and_cannot_mark_auto_as_human(service):
    client = quotes(service)
    body, manual = check(client)
    _, sessions, uid, settings = service
    with sessions.begin() as db:
        old = db.get(OrderCheck, manual["check_id"])
        old.origin = "legacy"
        auto = orders.preflight(db, uid, Draft(**body), settings, origin="automation")
        auto_id = auto.check_id
    assert client.post(f"/v1/orders/check/{auto_id}/presented").status_code == 409
    data = report(client)
    assert data["excluded"] == {"legacy": 1, "automation": 1}
    assert data["total_checks"] == 0


def test_frozen_context_policy_and_csv_omit_identity_and_free_text(service):
    client = quotes(service, current=97000)
    p = plan(service, side="sell", minutes=1, stop_loss_won=95000)
    body, result = check(client, side="sell", plan_id=p)
    a = result["analysis"]
    assert a["context"]["position_return_percent"] == "-3.00"
    assert a["context"]["stop_loss_won"] == 95000
    assert a["policy"]["panic_percent"] == -3
    presented(client, result)
    receipt = send(
        client, body, result, warning_acknowledged=True, trade_reason="private-reason-123"
    ).json()
    client.put(f"/v1/orders/{receipt['order_id']}/note", json={"text": "private-note-123"})
    exported = client.get("/v1/feedback/export").json()
    assert exported["rows"] == 1
    text = exported["csv"]
    assert "private-reason-123" not in text and "private-note-123" not in text
    assert "test@example.com" not in text
    rows = list(csv.DictReader(io.StringIO(text)))
    assert rows[0]["warnings"] == '["panic"]'
    assert rows[0]["trade_reason_recorded"] == "True"
    assert rows[0]["rule_version"] == a["version"]
    assert '"panic_percent": -3' in rows[0]["policy"]


def test_feedback_is_account_scoped_and_validates_period(service):
    from app.cli import create_user

    client = quotes(service)
    _, result = check(client)
    _, sessions, _, _ = service
    with sessions.begin() as db:
        create_user(db, "other-feedback@example.test", "another-password-123")
    token = client.post(
        "/v1/auth/login",
        json={
            "email": "other-feedback@example.test",
            "password": "another-password-123",
        },
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    assert client.post(f"/v1/orders/check/{result['check_id']}/presented").status_code == 404
    assert client.post(f"/v1/orders/check/{result['check_id']}/dismiss").status_code == 404
    assert report(client)["total_checks"] == 0
    assert client.get("/v1/feedback/export").json()["rows"] == 0
    assert client.get("/v1/feedback?days=0").status_code == 422
    assert client.get("/v1/feedback?days=366").status_code == 422
    assert client.get("/v1/feedback?offset=-1").status_code == 422


def test_feedback_pagination_includes_unsubmitted_checks(service):
    client = quotes(service)
    _, sessions, uid, _ = service
    _, result = check(client)
    with sessions.begin() as db:
        sample = db.get(OrderCheck, result["check_id"])
        for _ in range(52):
            db.add(
                OrderCheck(
                    user_id=uid,
                    draft=sample.draft,
                    analysis=sample.analysis,
                    messages=sample.messages,
                    allowed=True,
                    expires_at=sample.expires_at,
                )
            )
    first = report(client)
    second = client.get("/v1/feedback?offset=50").json()
    assert first["total_checks"] == second["total_checks"] == 53
    assert len(first["items"]) == 50 and first["next_offset"] == 50
    assert len(second["items"]) == 3 and second["next_offset"] is None
    assert not ({r["check_id"] for r in first["items"]} & {r["check_id"] for r in second["items"]})
    assert client.get("/v1/feedback/export").json()["rows"] == 53


def test_manual_deferral_reason_is_immutable_and_private_to_report(service):
    client = quotes(service)
    _, result = check(client)
    presented(client, result)
    url = f"/v1/orders/check/{result['check_id']}/dismiss"
    reason = "  급등 이후 진입 범위를 확인하기 위해 보류  "
    response = client.post(url, json={"reason": reason})
    assert response.status_code == 200
    assert response.json()["reason"] == reason.strip()
    row = report(client)["items"][0]
    assert row["decision_reason"] == reason.strip()
    assert row["defer_reason_recorded"] is True
    assert client.post(url, json={"reason": reason}).json() == response.json()
    assert client.post(url).json() == response.json()  # older clients do not erase text
    assert report(client)["items"][0]["decided_at"] == row["decided_at"]
    assert client.post(url, json={"reason": "다른 이유"}).status_code == 409
    exported = client.get("/v1/feedback/export").json()["csv"]
    assert reason.strip() not in exported
    assert "decision_reason" not in exported.splitlines()[0]
    values = list(csv.DictReader(io.StringIO(exported)))
    assert values[0]["defer_reason_recorded"] == "True"
    assert report(client)["items"][0]["order_id"] is None


def test_dismiss_reason_validation_and_submitted_check_cannot_be_rewritten(service):
    client = quotes(service, current=100000)
    body, result = check(client)
    url = f"/v1/orders/check/{result['check_id']}/dismiss"
    for payload in ({"reason": "x" * 1001}, {"reason": None}, {"unexpected": True}):
        assert client.post(url, json=payload).status_code == 422
    assert send(client, body, result).json()["status"] == "accepted"
    assert client.post(url, json={"reason": "거래 이후 변경"}).status_code == 409
    assert report(client)["items"][0]["decision_reason"] == ""


def test_blank_reason_and_preexisting_rows_remain_readable(service):
    client = quotes(service)
    _, result = check(client)
    url = f"/v1/orders/check/{result['check_id']}/dismiss"
    assert client.post(url, json={"reason": "   "}).status_code == 200
    row = report(client)["items"][0]
    assert row["decision_reason"] == ""
    assert row["defer_reason_recorded"] is False


def test_reason_migration_keeps_preexisting_check_records(service):
    from alembic import command
    from alembic.config import Config

    client = quotes(service)
    _, result = check(client)
    config = Config("alembic.ini")
    # Dedicated fixture schema only: simulate a database from before this column.
    command.downgrade(config, "20261023_replay")
    command.upgrade(config, "head")
    data = report(client)
    assert data["items"][0]["check_id"] == result["check_id"]
    assert data["items"][0]["decision_reason"] == ""
    assert data["items"][0]["defer_reason_recorded"] is False
