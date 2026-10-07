import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from starlette.websockets import WebSocketDisconnect

from app.api import create_app
from app.brokers.contracts import BrokerNotConfigured, BrokerOrder
from app.brokers.template import BrokerAdapterTemplate
from app.cli import create_user
from app.config import Settings
from app.logging_config import RedactTicket
from app.models import AuthSession, Order, OrderCheck, Quote, User, WsTicket, now
from app.security import digest


def draft(**changes):
    return {
        "symbol": "005930",
        "side": "buy",
        "quantity": 1,
        "limit_price_won": "72800",
        "order_type": "limit",
        "pilot_enabled": True,
        **changes,
    }


def checked(client, **changes):
    assert client.get("/v1/watchlist").status_code == 200
    body = draft(**changes)
    response = client.post("/v1/orders/check", json=body)
    assert response.status_code == 200, response.text
    return {**body, "check_id": response.json()["check_id"]}


def test_client_contract_and_cancel(service):
    client, sessions, user_id, _ = service
    assert client.get("/health/ready").status_code == 200
    quotes = client.get("/v1/watchlist").json()
    assert quotes["market_data_mode"] == "demo"
    assert isinstance(quotes["items"][0]["price_won"], str)
    assert quotes["items"][0]["source"] == "demo"
    assert client.get("/v1/predictions/005930").json()["status"] == "unavailable"
    body = checked(client)
    order = client.post("/v1/orders", json=body, headers={"Idempotency-Key": "one"}).json()
    assert order["status"] == "accepted"
    with sessions() as db:
        assert db.get(User, user_id).reserved_won == 72800
    for _ in range(2):
        assert client.post(f"/v1/orders/{order['order_id']}/cancel").json()["status"] == "cancelled"
    with sessions() as db:
        assert db.get(User, user_id).reserved_won == 0
    assert client.get("/v1/orders").json()["items"][0]["status"] == "cancelled"


def test_replay_before_expiry_and_staleness_checks(service):
    client, sessions, user_id, _ = service
    body = checked(client)
    result = client.post("/v1/orders", json=body, headers={"Idempotency-Key": "replay"})
    with sessions.begin() as db:
        db.get(OrderCheck, body["check_id"]).expires_at = now() - timedelta(minutes=5)
        db.get(Quote, "005930").as_of = now() - timedelta(minutes=5)
    replay = client.post("/v1/orders", json=body, headers={"Idempotency-Key": "replay"})
    assert replay.json() == result.json()
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 1
        assert db.get(User, user_id).reserved_won == 72800
    conflict = client.post(
        "/v1/orders", json={**body, "quantity": 2}, headers={"Idempotency-Key": "replay"}
    )
    assert conflict.status_code == 409


def test_same_check_cannot_create_two_orders(service):
    client, _, _, _ = service
    body = checked(client)
    assert (
        client.post("/v1/orders", json=body, headers={"Idempotency-Key": "a"}).json()["status"]
        == "accepted"
    )
    assert (
        client.post("/v1/orders", json=body, headers={"Idempotency-Key": "b"}).json()["status"]
        == "rejected"
    )


def test_final_balance_rechecked_and_pilot_off_keeps_limits(service):
    client, sessions, user_id, _ = service
    body = checked(client, pilot_enabled=False)
    with sessions.begin() as db:
        db.get(User, user_id).cash_won = 1
    response = client.post("/v1/orders", json=body, headers={"Idempotency-Key": "no-cash"})
    assert response.json()["status"] == "rejected"
    assert not client.post("/v1/orders/check", json=draft(pilot_enabled=False)).json()["allowed"]


def test_stale_quote_and_sell_quantity_are_rejected(service):
    client, sessions, _, _ = service
    client.get("/v1/watchlist")
    with sessions.begin() as db:
        db.get(Quote, "005930").as_of = now() - timedelta(minutes=1)
    assert not client.post("/v1/orders/check", json=draft()).json()["allowed"]
    client.get("/v1/watchlist")
    assert not client.post("/v1/orders/check", json=draft(side="sell", quantity=101)).json()[
        "allowed"
    ]


def test_concurrent_requests_share_one_order_and_reservation(service):
    client, sessions, user_id, _ = service
    body = checked(client)

    def send(_):
        return client.post(
            "/v1/orders", json=body, headers={"Idempotency-Key": "concurrent"}
        ).json()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(send, range(4)))
    assert len({r["order_id"] for r in results}) == 1
    with sessions() as db:
        assert db.get(User, user_id).reserved_won == 72800


def test_concurrent_different_keys_cannot_overspend(service):
    client, sessions, user_id, _ = service
    with sessions.begin() as db:
        db.get(User, user_id).cash_won = 72800
    bodies = [checked(client), checked(client)]

    def send(i):
        return client.post(
            "/v1/orders", json=bodies[i], headers={"Idempotency-Key": f"key-{i}"}
        ).json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, range(2)))
    assert sorted(r["status"] for r in results) == ["accepted", "rejected"]
    with sessions() as db:
        assert db.get(User, user_id).reserved_won == 72800


def test_user_isolation(service):
    client, sessions, _, _ = service
    body = checked(client)
    first = client.post("/v1/orders", json=body, headers={"Idempotency-Key": "owner"}).json()
    with sessions.begin() as db:
        create_user(db, "other@example.com", "another-password-123")
    token = client.post(
        "/v1/auth/login", json={"email": "other@example.com", "password": "another-password-123"}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    assert client.get("/v1/orders").json()["items"] == []
    assert client.post(f"/v1/orders/{first['order_id']}/cancel").status_code == 404
    assert (
        client.post("/v1/orders", json=body, headers={"Idempotency-Key": "stolen"}).json()["status"]
        == "rejected"
    )


def test_websocket_contract_and_ticket_single_use(service):
    client, _, _, _ = service
    ticket = client.post("/v1/ws-ticket").json()["ticket"]
    with client.websocket_connect(f"/v1/ws?ticket={ticket}") as ws:
        ws.send_json({"type": "subscribe", "channel": "quotes"})
        quote = ws.receive_json()
        assert quote["type"] == "quote"
        assert quote["data"]["sequence"] > 0
        assert quote["data"]["source"] == "demo"
        ws.send_json({"type": "ping"})
        for _ in range(4):
            if ws.receive_json()["type"] == "pong":
                break
        else:
            pytest.fail("pong missing")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/v1/ws?ticket={ticket}"):
            pass


def test_expired_ticket_and_revoked_session_rejected(service):
    client, sessions, _, _ = service
    ticket = client.post("/v1/ws-ticket").json()["ticket"]
    with sessions.begin() as db:
        db.get(WsTicket, digest(ticket)).expires_at = now() - timedelta(seconds=1)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/v1/ws?ticket={ticket}"):
            pass
    assert client.post("/v1/auth/logout").status_code == 200
    assert client.get("/v1/orders").status_code == 401


def test_disabled_broker_has_no_synthetic_fallback(service):
    _, sessions, _, settings = service
    disabled = Settings(
        database_url=settings.database_url, market_data_mode="disabled", _env_file=None
    )
    with TestClient(create_app(disabled, sessions)) as client:
        token = client.post(
            "/v1/auth/login", json={"email": "test@example.com", "password": "test-password-123"}
        ).json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        assert client.get("/v1/watchlist").json()["items"] == []
        assert not client.get("/v1/integrations/broker").json()["configured"]
        assert not client.post("/v1/orders/check", json=draft()).json()["allowed"]
    with pytest.raises(BrokerNotConfigured):
        BrokerAdapterTemplate().place_order(BrokerOrder("account", "005930", "buy", 1, 1, "key"))


def test_invalid_input_and_auth(service):
    client, _, _, _ = service
    for change in [
        {"quantity": 0},
        {"quantity": True},
        {"limit_price_won": 1},
        {"limit_price_won": "-1"},
        {"order_type": "market"},
    ]:
        assert client.post("/v1/orders/check", json=draft(**change)).status_code == 422
    assert (
        client.post(
            "/v1/auth/login", json={"email": "test@example.com", "password": "wrong"}
        ).status_code
        == 401
    )
    client.headers.pop("Authorization")
    assert client.get("/v1/watchlist").status_code == 401


def test_sequence_persists_across_requests(service):
    client, _, _, _ = service
    first = client.get("/v1/watchlist").json()["items"]
    second = client.get("/v1/watchlist").json()["items"]
    assert all(b["sequence"] > a["sequence"] for a, b in zip(first, second, strict=True))


def test_session_expiry(service):
    client, sessions, _, _ = service
    token = client.headers["Authorization"].split()[1]
    with sessions.begin() as db:
        db.get(AuthSession, digest(token)).expires_at = now() - timedelta(seconds=1)
    assert client.post("/v1/ws-ticket").status_code == 401


def test_handshake_log_ticket_redacted():
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        "",
        1,
        "WebSocket %s [accepted]",
        ("/v1/ws?ticket=secret",),
        None,
    )
    RedactTicket().filter(record)
    assert "secret" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_commit_failure_never_returns_accepted(service):
    client, sessions, user_id, settings = service
    body = checked(client)

    class FailingCommit:
        @contextmanager
        def begin(self):
            with sessions.begin() as db:
                yield db
                raise RuntimeError("simulated commit failure")

    with TestClient(
        create_app(settings, FailingCommit()), raise_server_exceptions=False
    ) as failing:
        response = failing.post(
            "/v1/orders",
            json=body,
            headers={
                "Authorization": client.headers["Authorization"],
                "Idempotency-Key": "commit-fails",
            },
        )
        assert response.status_code == 500
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        assert db.get(User, user_id).reserved_won == 0
