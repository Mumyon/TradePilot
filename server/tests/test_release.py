from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from test_portfolio import order

from app.models import Order, User
from app.security import passwords


def test_signup_validation_login_and_no_holdings(service):
    client, sessions, _, _ = service
    body = dict(
        email=" New@Example.test ",
        password="a-new-password-123",
        password_confirmation="a-new-password-123",
    )
    assert client.post("/v1/auth/signup", json={**body, "email": "bad"}).status_code == 422
    assert (
        client.post(
            "/v1/auth/signup", json={**body, "password_confirmation": "wrong-password"}
        ).status_code
        == 422
    )
    response = client.post("/v1/auth/signup", json=body)
    assert response.status_code == 201
    assert client.post("/v1/auth/signup", json=body).status_code == 409
    with sessions() as db:
        user = db.scalar(select(User).where(User.email == "new@example.test"))
        assert passwords.verify(body["password"], user.password_hash)
        assert user.password_hash != body["password"]
    login = client.post(
        "/v1/auth/login", json={"email": "new@example.test", "password": body["password"]}
    )
    assert login.status_code == 200
    client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
    account = client.get("/v1/account").json()
    assert account["cash_won"] == "10000000"
    assert account["holdings"] == []


def test_concurrent_signup_unique(service):
    client, _, _, _ = service
    body = dict(
        email="race@example.test",
        password="race-test-password",
        password_confirmation="race-test-password",
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: client.post("/v1/auth/signup", json=body).status_code, range(2))
        )
    assert sorted(results) == [201, 409]


def test_review_note_preserves_order_snapshot_and_ownership(service):
    client, sessions, _, _ = service
    accepted, _ = order(client)
    ident = accepted["order_id"]
    with sessions() as db:
        original = db.get(Order, ident).analysis
    result = client.put(f"/v1/orders/{ident}/note", json={"text": "다음에는 진입 조건 확인"})
    assert result.status_code == 200
    with sessions() as db:
        row = db.get(Order, ident)
        assert row.analysis == original
        assert row.review_note == "다음에는 진입 조건 확인"
    assert client.get("/v1/journal").json()["items"][0]["review_note"] == "다음에는 진입 조건 확인"
    assert client.put(f"/v1/orders/{ident}/note", json={"text": "x" * 2001}).status_code == 422
    client.post(
        "/v1/auth/signup",
        json=dict(
            email="other@example.test",
            password="another-password",
            password_confirmation="another-password",
        ),
    )
    token = client.post(
        "/v1/auth/login", json=dict(email="other@example.test", password="another-password")
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    assert client.put(f"/v1/orders/{ident}/note", json={"text": "overwrite"}).status_code == 404


def test_status_contains_no_model_path_or_secrets(service):
    client, _, _, settings = service
    settings.prediction_model_path = "/private/secret/model.json"
    result = client.get("/v1/system/status")
    assert result.status_code == 200
    assert result.json()["model_configured"]
    assert "/private/" not in result.text
    client.headers.clear()
    assert client.get("/v1/system/status").status_code == 401


def test_candle_history_never_mixes_sources_or_unfinished_bars(service):
    from datetime import timedelta

    from app.models import Candle, now
    from app.services.candles import history

    _, sessions, _, _ = service
    at = now() - timedelta(minutes=10)
    with sessions.begin() as db:
        for source, price in [("provider_a", 70000), ("provider_b", 80000)]:
            db.add(
                Candle(
                    symbol="005930",
                    interval="5m",
                    opened_at=at,
                    source=source,
                    open_won=price,
                    high_won=price,
                    low_won=price,
                    close_won=price,
                    volume=1,
                    complete=True,
                )
            )
        db.add(
            Candle(
                symbol="005930",
                interval="5m",
                opened_at=now() - timedelta(minutes=1),
                source="provider_a",
                open_won=1,
                high_won=1,
                low_won=1,
                close_won=1,
                volume=1,
                complete=False,
            )
        )
    with sessions() as db:
        result = history(db, "005930", "5m", None, "disabled")
        assert len(result["items"]) == 1
        assert result["source"] == "provider_a"
        assert result["items"][0]["close_won"] == "70000"


def test_twenty_rejected_order_replays_never_reserve_or_fill(service):
    from sqlalchemy import func
    from test_api import draft

    from app.models import Fill

    client, sessions, uid, _ = service
    client.get("/v1/watchlist")
    for n in range(20):
        body = draft(quantity=1000000 if n % 2 else 100)
        check = client.post("/v1/orders/check", json=body).json()
        assert not check["allowed"]
        body["check_id"] = check["check_id"]
        headers = {"Idempotency-Key": f"rejected-{n}"}
        first = client.post("/v1/orders", json=body, headers=headers).json()
        second = client.post("/v1/orders", json=body, headers=headers).json()
        assert first == second
        assert first["status"] == "rejected"
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 20
        assert db.scalar(select(func.count()).select_from(Fill)) == 0
        assert db.get(User, uid).reserved_won == 0
