"""Deterministic real-source paper lifecycle, without credentials or brokerage orders."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.brokers.contracts import MarketQuote
from app.brokers.toss import TossMarketData
from app.config import Settings
from app.models import Fill, Holding, MarketCalendar, Order, Quote, User
from app.services import journal, market_hours, orders, portfolio, risk
from app.services.fees import fee
from app.services.market import publish_quote


@pytest.fixture
def live(service, monkeypatch):
    client, sessions, user_id, settings = service
    settings.market_data_mode = "toss"
    clock = [datetime(2026, 11, 9, 1, tzinfo=UTC)]
    for module in (orders, portfolio, risk, market_hours, journal):
        monkeypatch.setattr(module, "now", lambda: clock[0])
    with sessions.begin() as db:
        db.add(
            MarketCalendar(
                source="toss_kr",
                checked_at=clock[0],
                payload={
                    "today": {
                        "date": "2026-11-09",
                        "integrated": {
                            "regularMarket": {
                                "startTime": "2026-11-09T09:00:00+09:00",
                                "singlePriceAuctionStartTime": "2026-11-09T15:20:00+09:00",
                                "endTime": "2026-11-09T15:30:00+09:00",
                            }
                        },
                    }
                },
            )
        )
        db.get(Holding, (user_id, "005930")).quantity = 0
        db.get(Holding, (user_id, "005930")).cost_won = 0
        publish_quote(db, MarketQuote("005930", 72000, clock[0], "toss_kr"))
    return service, clock


def place(live, key, side="buy", price=72000, quantity=2):
    (client, sessions, _, _), clock = live
    body = dict(
        symbol="005930",
        side=side,
        quantity=quantity,
        limit_price_won=str(price),
        order_type="limit",
        pilot_enabled=True,
    )
    checked = client.post("/v1/orders/check", json=body).json()
    assert checked["allowed"], checked
    response = client.post(
        "/v1/orders",
        headers={"Idempotency-Key": key},
        json={
            **body,
            "check_id": checked["check_id"],
            "warning_acknowledged": True,
            "high_risk_acknowledged": True,
            "trade_reason": "분할 매매 계획 검증",
        },
    ).json()
    assert response["status"] == "accepted", response
    with sessions.begin() as db:
        db.get(Order, response["order_id"]).created_at = clock[0]
    return response["order_id"]


def tick(live, price, *, age=0, source="toss_kr", executable=True):
    (_, sessions, user_id, settings), clock = live
    with sessions.begin() as db:
        publish_quote(
            db,
            MarketQuote(
                "005930", price, clock[0] - timedelta(seconds=age), source, executable=executable
            ),
        )
    with sessions.begin() as db:
        portfolio.settle(db, user_id, settings)
        # Keep persisted event times on the fixture clock, not wall-clock time.
        for fill in db.scalars(select(Fill).where(Fill.user_id == user_id)):
            fill.created_at = fill.quote_as_of


def test_live_buy_sell_cancel_balances_and_journal(live):
    (client, sessions, user_id, _), clock = live
    buy = place(live, "buy")
    # The acceptance quote is not a new execution.
    tick(live, 72000)
    assert client.get("/v1/fills").json()["items"] == []
    clock[0] += timedelta(seconds=1)
    tick(live, 72100)
    assert client.get("/v1/orders").json()["items"][0]["status"] == "accepted"
    clock[0] += timedelta(seconds=1)
    tick(live, 71900)
    account = client.get("/v1/account").json()
    basis = 143800 + fee(143800)
    assert int(account["cash_won"]) == 10000000 - basis
    assert account["reserved_won"] == "0"
    with sessions() as db:
        assert db.get(Holding, (user_id, "005930")).quantity == 2
    # Repeated worker invocations must not duplicate fills.
    tick(live, 71900)
    assert len(client.get("/v1/fills").json()["items"]) == 1
    sell = place(live, "sell", side="sell", price=73000)
    clock[0] += timedelta(seconds=1)
    tick(live, 74000)
    pnl = 148000 - fee(148000) - basis
    assert int(client.get("/v1/account").json()["realized_pnl_won"]) == pnl
    cancelled = place(live, "cancel", price=70000)
    assert client.post(f"/v1/orders/{cancelled}/cancel").json()["status"] == "cancelled"
    clock[0] += timedelta(seconds=1)
    tick(live, 69000)
    account = client.get("/v1/account").json()
    assert int(account["cash_won"]) == 10000000 + pnl
    assert account["reserved_won"] == "0"
    journal = client.get("/v1/journal").json()["items"]
    records = {r["order_id"]: r for r in journal}
    assert records[buy]["fill"]["source"] == "toss_kr"
    assert int(records[sell]["fill"]["realized_pnl_won"]) == pnl
    assert records[cancelled]["fill"] is None


def test_rest_delay_future_wrong_source_never_fill(live):
    (client, sessions, user_id, settings), clock = live
    place(live, "blocked")
    clock[0] += timedelta(seconds=20)
    tick(live, 71000, executable=False)
    tick(live, 71000, age=18)
    assert client.get("/v1/fills").json()["items"] == []
    # Future observations and a different provider are not executable.
    for source, timestamp in [
        ("toss_kr", clock[0] + timedelta(seconds=5)),
        ("namuh_krx", clock[0]),
    ]:
        with sessions.begin() as db:
            q = db.get(Quote, "005930")
            q.source, q.as_of, q.price_won = source, timestamp, 71000
        with sessions.begin() as db:
            portfolio.settle(db, user_id, settings)
    assert client.get("/v1/fills").json()["items"] == []
    with sessions.begin() as db:
        db.get(Quote, "005930").as_of = clock[0] - timedelta(seconds=30)
        db.get(Quote, "005930").source = "toss_kr"
    tick(live, 71000)
    assert len(client.get("/v1/fills").json()["items"]) == 1


@pytest.mark.parametrize("mode", ["closed", "holiday", "unavailable", "expired_calendar"])
def test_calendar_blocks_and_day_order_releases_reservations(live, mode):
    (client, sessions, user_id, settings), clock = live
    buy = place(live, "day-order")
    with sessions.begin() as db:
        row = db.get(MarketCalendar, "toss_kr")
        if mode == "closed":
            clock[0] = clock[0].replace(hour=6, minute=20)
            row.checked_at = clock[0]
        elif mode == "holiday":
            row.payload = {"today": {"date": "2026-11-09"}}
        elif mode == "unavailable":
            db.delete(row)
        else:
            row.checked_at -= timedelta(minutes=6)
    tick(live, 71000)
    assert client.get("/v1/fills").json()["items"] == []
    body = dict(
        symbol="005930",
        side="buy",
        quantity=1,
        limit_price_won="70000",
        order_type="limit",
        pilot_enabled=False,
    )
    assert not client.post("/v1/orders/check", json=body).json()["allowed"]
    if mode != "closed":
        # Calendar failures pause settlement; cancellation still always works.
        client.post(f"/v1/orders/{buy}/cancel")
    with sessions() as db:
        assert db.get(Order, buy).status == "cancelled"
        assert db.get(User, user_id).reserved_won == 0
        assert db.scalar(select(func.count()).select_from(Fill)) == 0


def test_subscription_priority_survives_ranking_changes():
    provider = TossMarketData(Settings(database_url="postgresql://unused", _env_file=None))
    provider.symbols = [f"{i:06d}" for i in range(100)]
    provider.set_priority_symbols(["999999", "888888", "999999"])
    assert provider.subscription_symbols()[:2] == ["999999", "888888"]
    assert len(provider.subscription_symbols()) == 100
    provider.symbols = ["777777"]
    assert provider.subscription_symbols() == ["999999", "888888", "777777"]


def test_sell_expiry_releases_quantity_and_next_day_orders_do_not_fill(live):
    (client, sessions, user_id, settings), clock = live
    with sessions.begin() as db:
        h = db.get(Holding, (user_id, "005930"))
        h.quantity, h.cost_won = 5, 360000
    sell = place(live, "sell-expiry", side="sell", price=80000)
    with sessions() as db:
        assert db.get(Holding, (user_id, "005930")).reserved == 2
    # Even after a process restart/calendar outage, yesterday's order expires.
    clock[0] += timedelta(days=1)
    tick(live, 90000)
    with sessions() as db:
        h = db.get(Holding, (user_id, "005930"))
        assert h.reserved == 0 and h.quantity == 5
        assert db.get(Order, sell).status == "cancelled"
        assert db.get(User, user_id).cash_won == 10000000


def test_delayed_opening_and_null_holiday_session(live):
    (_, sessions, _, settings), clock = live
    with sessions.begin() as db:
        row = db.get(MarketCalendar, "toss_kr")
        row.payload = {
            "today": {
                "date": "2026-11-09",
                "integrated": {
                    "regularMarket": {
                        "startTime": "2026-11-09T10:30:00+09:00",
                        "singlePriceAuctionStartTime": "2026-11-09T16:20:00+09:00",
                    }
                },
            }
        }
    with sessions() as db:
        assert not market_hours.status(db, settings)["can_trade"]
    with sessions.begin() as db:
        db.get(MarketCalendar, "toss_kr").payload = {
            "today": {"date": "2026-11-09", "integrated": None}
        }
    with sessions() as db:
        assert market_hours.status(db, settings)["state"] == "closed"


def test_premarket_test_mode_fills_only_opted_in_orders(live, monkeypatch):
    from app.brokers.demo import DemoMarketData

    monkeypatch.setattr(DemoMarketData, "status", lambda self: {}, raising=False)
    (client, sessions, user_id, settings), clock = live
    regular_order = place(live, "regular")
    clock[0] = datetime(2026, 11, 9, 7, tzinfo=market_hours.KST)
    with sessions.begin() as db:
        db.get(MarketCalendar, "toss_kr").checked_at = clock[0]
        db.get(Quote, "005930").as_of = clock[0] - timedelta(days=1)

    draft = dict(
        symbol="005930",
        side="buy",
        quantity=1,
        limit_price_won="72000",
        pilot_enabled=False,
        test_mode=True,
    )
    assert not client.post("/v1/orders/check", json=draft).json()["allowed"]
    settings.paper_test_date = clock[0].date()
    assert client.get("/v1/system/status").json()["test_mode_available"]
    assert not client.post("/v1/orders/check", json={**draft, "test_mode": False}).json()["allowed"]

    for side in ("buy", "sell"):
        # A stale price of 72,000 must not block either side of a test trade.
        limit = "71500" if side == "buy" else "72500"
        body = {**draft, "side": side, "limit_price_won": limit}
        check = client.post("/v1/orders/check", json=body).json()
        assert check["allowed"], check
        headers = {"Idempotency-Key": f"test-{side}"}
        submission = {**body, "check_id": check["check_id"]}
        result = client.post("/v1/orders", json=submission, headers=headers).json()
        assert result["status"] == "filled", result
        assert client.post("/v1/orders", json=submission, headers=headers).json() == result

    with sessions() as db:
        assert db.get(Order, regular_order).status == "accepted"
        assert db.get(Holding, (user_id, "005930")).quantity == 0
        fills = db.scalars(select(Fill)).all()
        assert {fill.side: fill.price_won for fill in fills} == {"buy": 71500, "sell": 72500}
        assert all(fill.source == "test_mode" for fill in fills)

    with sessions.begin() as db:
        db.delete(db.get(Quote, "005930"))
    body = {**draft, "limit_price_won": "71500"}
    check = client.post("/v1/orders/check", json=body).json()
    assert check["allowed"], check
    assert any("입력한 지정가" in message for message in check["messages"])
    result = client.post(
        "/v1/orders",
        json={**body, "check_id": check["check_id"]},
        headers={"Idempotency-Key": "test-without-quote"},
    ).json()
    assert result["status"] == "filled", result
    with sessions() as db:
        fill = db.scalar(select(Fill).where(Fill.order_id == result["order_id"]))
        assert (fill.price_won, fill.source) == (71500, "test_mode")
        assert db.get(Quote, "005930") is None

    clock[0] = clock[0].replace(hour=9)
    assert not client.get("/v1/system/status").json()["test_mode_available"]
