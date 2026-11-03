from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import func, select
from test_api import checked

from app.brokers.contracts import MarketQuote
from app.models import Candle, Fill, Holding, Order, Quote, User, now
from app.services import portfolio
from app.services.fees import fee, reserve
from app.services.market import publish_quote


def order(client, key="one", **changes):
    body = checked(client, **changes)
    body.update(
        warning_acknowledged=True, high_risk_acknowledged=True, trade_reason="검증용 계획 주문"
    )
    response = client.post("/v1/orders", json=body, headers={"Idempotency-Key": key})
    assert response.status_code == 200, response.text
    return response.json(), body


def settle(service, price=72800):
    _, sessions, user_id, settings = service
    with sessions.begin() as db:
        publish_quote(db, MarketQuote("005930", price, now(), "demo"))
    with sessions.begin() as db:
        portfolio.settle(db, user_id, settings)


def test_account_settings_plans_watchlist(service):
    client, _, _, _ = service
    client.get("/v1/watchlist")
    account = client.get("/v1/account").json()
    assert account["cash_won"] == "10000000"
    assert len(account["holdings"]) == 2
    prefs = dict(
        order_limit_won=500000,
        daily_loss_limit_won=100000,
        cooldown_seconds=120,
        trading_rules="분할 매수",
        trading_paused=False,
    )
    assert client.put("/v1/settings", json=prefs).json() == prefs
    assert client.get("/v1/settings").json() == prefs
    assert client.put("/v1/settings", json={**prefs, "order_limit_won": -1}).status_code == 422
    plan = dict(
        symbol="005930",
        side="buy",
        entry_condition="72000원 이하",
        stop_loss_won=70000,
        max_amount_won=500000,
        split_order=True,
    )
    assert client.post("/v1/plans", json=plan).status_code == 200
    assert client.get("/v1/plans").json()["items"][0]["entry_condition"] == "72000원 이하"
    for _ in range(2):
        assert client.delete("/v1/watchlist/005930").status_code == 200
    assert not any(q["symbol"] == "005930" for q in client.get("/v1/watchlist").json()["items"])
    for _ in range(2):
        assert client.put("/v1/watchlist/005930").status_code == 200
    assert len(client.get("/v1/watchlist").json()["items"]) == 2
    assert client.get("/v1/symbols?q=삼성").json()["items"][0]["watched"]
    assert client.put("/v1/watchlist/UNKNOWN").status_code == 404


def test_buy_sell_cost_and_pnl(service):
    client, sessions, user_id, _ = service
    accepted, body = order(client, quantity=5)
    assert accepted["status"] == "accepted"
    settle(service, 72000)
    fills = client.get("/v1/fills").json()["items"]
    assert fills[0]["price_won"] == "72000"
    assert fills[0]["fee_won"] == str(fee(360000))
    assert client.post(f"/v1/orders/{accepted['order_id']}/cancel").json()["status"] == "filled"
    replay = client.post("/v1/orders", json=body, headers={"Idempotency-Key": "one"}).json()
    assert replay["status"] == "filled"
    with sessions() as db:
        h = db.get(Holding, (user_id, "005930"))
        assert h.quantity == 105
        assert h.cost_won == 7280000 + 360000 + fee(360000)
        basis = h.cost_won * 5 // 105
        assert db.get(User, user_id).reserved_won == 0
    order(client, key="sell", side="sell", quantity=5, limit_price_won="73000")
    settle(service, 74000)
    fills = client.get("/v1/fills").json()["items"]
    assert fills[0]["realized_pnl_won"] == str(370000 - fee(370000) - basis)
    with sessions() as db:
        assert db.get(User, user_id).cash_won == 10000000 - 360000 - fee(360000) + 370000 - fee(
            370000
        )
        assert db.get(Holding, (user_id, "005930")).quantity == 100


def test_limit_stale_cancel_and_fees(service):
    client, sessions, user_id, settings = service
    accepted, _ = order(client, limit_price_won="71000")
    settle(service, 72000)
    assert client.get("/v1/fills").json()["items"] == []
    with sessions.begin() as db:
        db.get(Quote, "005930").price_won = 70000
        db.get(Quote, "005930").as_of = now() - timedelta(minutes=2)
        portfolio.settle(db, user_id, settings)
    assert client.get("/v1/fills").json()["items"] == []
    client.post(f"/v1/orders/{accepted['order_id']}/cancel")
    settle(service, 70000)
    assert client.get("/v1/fills").json()["items"] == []
    with sessions.begin() as db:
        db.get(User, user_id).cash_won = 72800
    body = checked(client)
    assert (
        client.post("/v1/orders", json=body, headers={"Idempotency-Key": "fee"}).json()["status"]
        == "rejected"
    )


def test_concurrent_settlement_exactly_once(service):
    client, sessions, user_id, settings = service
    order(client)
    with sessions.begin() as db:
        publish_quote(db, MarketQuote("005930", 72800, now(), "demo"))

    def match(_):
        with sessions.begin() as db:
            portfolio.settle(db, user_id, settings)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(match, range(4)))
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Fill)) == 1
        assert db.get(User, user_id).cash_won == 10000000 - reserve(72800)
        assert db.get(User, user_id).reserved_won == 0


def test_candles_and_missing_cost(service):
    client, sessions, user_id, _ = service
    for interval in ["1m", "5m", "15m", "1h", "1d"]:
        response = client.get(f"/v1/market/005930/candles?interval={interval}")
        data = response.json()
        assert response.status_code == 200, response.text
        assert len(data["items"]) == 120
        assert data["source"] == "demo" and not data["stale"]
        assert all(row["complete"] for row in data["items"])
        assert (
            data["items"]
            == client.get(f"/v1/market/005930/candles?interval={interval}").json()["items"]
        )
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Candle)) == 600
    with sessions.begin() as db:
        db.get(Holding, (user_id, "005930")).cost_won = None
    order(client, side="sell")
    settle(service)
    assert client.get("/v1/fills").json()["items"][0]["realized_pnl_won"] is None
    assert not client.get("/v1/account").json()["realized_pnl_complete"]


def test_cancel_fill_race(service):
    client, sessions, user_id, settings = service
    accepted, _ = order(client)
    with sessions.begin() as db:
        publish_quote(db, MarketQuote("005930", 72800, now(), "demo"))
    from app.services.orders import cancel

    def run(action):
        with sessions.begin() as db:
            if action:
                portfolio.settle(db, user_id, settings)
            else:
                cancel(db, user_id, accepted["order_id"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, [True, False]))
    with sessions() as db:
        status = db.get(Order, accepted["order_id"]).status
        assert status in ["filled", "cancelled"]
        assert db.get(User, user_id).reserved_won == 0
        assert db.scalar(select(func.count()).select_from(Fill)) == (1 if status == "filled" else 0)


def test_one_hundred_order_lifecycles(service):
    client, sessions, user_id, _ = service
    filled = 0
    for i in range(100):
        # Alternate completed buys/sells and non-marketable cancelled orders.
        side = "buy" if i % 2 == 0 else "sell"
        price = "70000" if i % 5 == 0 and side == "buy" else "72800"
        accepted, body = order(client, key=f"scenario-{i}", side=side, limit_price_won=price)
        assert accepted["status"] == "accepted"
        if i % 5 == 0:
            client.post(f"/v1/orders/{accepted['order_id']}/cancel")
        else:
            settle(service)
            filled += 1
        replay = client.post(
            "/v1/orders", json=body, headers={"Idempotency-Key": f"scenario-{i}"}
        ).json()
        assert replay["status"] == ("cancelled" if i % 5 == 0 else "filled")
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Fill)) == filled == 80
        assert db.scalar(select(func.count()).select_from(Order)) == 100
        assert db.get(User, user_id).reserved_won == 0
        assert db.get(Holding, (user_id, "005930")).reserved == 0
        assert db.get(User, user_id).cash_won == 10000000 - 80 * fee(72800)


def test_upgrade_preserves_legacy_pending_reservations(database):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    _, sessions = database
    config = Config("alembic.ini")
    command.downgrade(config, "c060d541e2e4")
    with sessions.begin() as db:
        db.execute(
            text("""INSERT INTO users (id,email,password_hash,enabled,cash_won,reserved_won,
            order_limit_won,daily_loss_limit_won) VALUES
            ('legacy','legacy@example.test','unused',true,100000,72800,1000000,1000000)""")
        )
        db.execute(text("INSERT INTO symbols (symbol,name) VALUES ('005930','삼성전자')"))
        db.execute(
            text("""INSERT INTO holdings (user_id,symbol,quantity,reserved)
            VALUES ('legacy','005930',10,0)""")
        )
        db.execute(
            text("""INSERT INTO orders (id,user_id,idempotency_key,request_body,symbol,side,
            quantity,limit_price_won,status,created_at) VALUES
            ('old-order','legacy','old-key','{}','005930','buy',1,72800,'accepted',now())""")
        )
    command.upgrade(config, "head")
    with sessions() as db:
        assert db.get(Order, "old-order").status == "accepted"
        assert db.get(Order, "old-order").reserved_cash_won == 72800
        assert db.get(User, "legacy").reserved_won == 72800
        assert db.get(Holding, ("legacy", "005930")).cost_won is None


def test_fill_transaction_failure_rolls_back(service):
    import pytest

    client, sessions, user_id, settings = service
    accepted, _ = order(client)
    with sessions.begin() as db:
        publish_quote(db, MarketQuote("005930", 72800, now(), "demo"))
    with pytest.raises(RuntimeError):
        with sessions.begin() as db:
            portfolio.settle(db, user_id, settings)
            raise RuntimeError("simulated failure before commit")
    with sessions() as db:
        assert db.get(Order, accepted["order_id"]).status == "accepted"
        assert db.get(User, user_id).cash_won == 10000000
        assert db.get(User, user_id).reserved_won == reserve(72800)
        assert db.get(Holding, (user_id, "005930")).quantity == 100
        assert db.scalar(select(func.count()).select_from(Fill)) == 0


def test_account_plan_watchlist_isolation(service):
    from app.cli import create_user

    client, sessions, _, _ = service
    client.post(
        "/v1/plans",
        json=dict(
            symbol="005930", side="buy", entry_condition="private plan", max_amount_won=100000
        ),
    )
    client.delete("/v1/watchlist/005930")
    with sessions.begin() as db:
        create_user(db, "second@example.test", "another-test-password")
    token = client.post(
        "/v1/auth/login", json=dict(email="second@example.test", password="another-test-password")
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    assert client.get("/v1/plans").json()["items"] == []
    assert client.get("/v1/account").json()["holdings"] == []
    assert len(client.get("/v1/watchlist").json()["items"]) == 2
