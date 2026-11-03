from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from test_api import draft

from app.brokers.contracts import MarketQuote
from app.models import Fill, Holding, Order, TradePlan, User, now
from app.services.market import publish_quote


def quotes(service, base=100000, current=103000):
    client, sessions, user_id, _ = service
    at = now()
    with sessions.begin() as db:
        publish_quote(db, MarketQuote("005930", base, at - timedelta(minutes=10), "demo"))
        publish_quote(db, MarketQuote("005930", current, at, "demo"))
        db.get(Holding, (user_id, "005930")).cost_won = 10000000
    return client


def check(client, **changes):
    body = draft(limit_price_won="103000", **changes)
    response = client.post("/v1/orders/check", json=body)
    assert response.status_code == 200, response.text
    return body, response.json()


def item(result, code):
    return next(i for i in result["analysis"]["behavior"]["items"] if i["code"] == code)


def send(client, body, result, key="risk", **acks):
    return client.post(
        "/v1/orders",
        json={**body, "check_id": result["check_id"], **acks},
        headers={"Idempotency-Key": key},
    )


def plan(service, side="buy", minutes=20, **extra):
    _, sessions, user_id, _ = service
    with sessions.begin() as db:
        p = TradePlan(
            user_id=user_id,
            symbol="005930",
            side=side,
            entry_condition="사전 계획",
            entry_min_won=extra.pop("entry_min_won", 90000),
            entry_max_won=extra.pop("entry_max_won", 110000),
            max_amount_won=extra.pop("max_amount_won", 1000000),
            split_order=extra.pop("split_order", False),
            created_at=now() - timedelta(minutes=minutes),
            **extra,
        )
        db.add(p)
        db.flush()
        return p.id


def history(service, losses, minutes=5):
    _, sessions, user_id, _ = service
    with sessions.begin() as db:
        for i, pnl in enumerate(losses):
            stamp = now() - timedelta(minutes=minutes + i)
            o = Order(
                user_id=user_id,
                symbol="005930",
                side="sell",
                quantity=1,
                limit_price_won=100000,
                status="filled",
                idempotency_key=f"past-{i}",
                request_body={},
                created_at=stamp,
            )
            db.add(o)
            db.flush()
            db.add(
                Fill(
                    order_id=o.id,
                    user_id=user_id,
                    symbol="005930",
                    side="sell",
                    quantity=1,
                    price_won=100000,
                    fee_won=15,
                    realized_pnl_won=pnl,
                    source="demo",
                    quote_as_of=stamp,
                    created_at=stamp,
                )
            )


@pytest.mark.parametrize("price,expected", [(102999, "clear"), (103000, "hit"), (103001, "hit")])
def test_fomo_boundary(service, price, expected):
    client = quotes(service, current=price)
    _, result = check(client)
    assert item(result, "fomo")["status"] == expected
    assert result["allowed"]
    assert result["analysis"]["behavior"]["score"] == (30 if expected == "hit" else 0)


@pytest.mark.parametrize("price,expected", [(97001, "clear"), (97000, "hit"), (96999, "hit")])
def test_panic_boundary(service, price, expected):
    client = quotes(service, current=price)
    _, result = check(client, side="sell")
    assert item(result, "panic")["status"] == expected


def test_preexisting_plan_exemptions_and_late_plan(service):
    client = quotes(service)
    old = plan(service)
    _, result = check(client, plan_id=old)
    assert item(result, "fomo")["status"] == "exempt"
    late = plan(service, minutes=1)
    _, result = check(client, plan_id=late)
    assert item(result, "fomo")["status"] == "hit"
    stop = plan(service, side="sell", stop_loss_won=98000)
    quotes(service, current=97000)
    _, result = check(client, side="sell", plan_id=stop)
    assert item(result, "panic")["status"] == "exempt"


def test_panic_requires_loss_and_known_basis(service):
    client = quotes(service, current=97000)
    _, sessions, user_id, _ = service
    with sessions.begin() as db:
        db.get(Holding, (user_id, "005930")).cost_won = 9000000
    _, result = check(client, side="sell")
    assert item(result, "panic")["status"] == "clear"
    with sessions.begin() as db:
        db.get(Holding, (user_id, "005930")).cost_won = None
    _, result = check(client, side="sell")
    assert item(result, "panic")["status"] == "unavailable"
    assert result["analysis"]["behavior"]["partial"]


@pytest.mark.parametrize(
    "losses,age,expected",
    [
        ([-1, -1, -1], 29, "hit"),
        ([-1, -1, -1], 31, "clear"),
        ([-1, 0, -1], 5, "clear"),
        ([-1, -1], 5, "clear"),
        ([-1, None, -1], 5, "unavailable"),
    ],
)
def test_revenge(service, losses, age, expected):
    client = quotes(service, current=100000)
    history(service, losses, minutes=age)
    _, result = check(client)
    assert item(result, "revenge")["status"] == expected
    _, result = check(client, side="sell")
    assert item(result, "revenge")["status"] == "not_applicable"


def test_revenge_presaved_split_plan(service):
    client = quotes(service, current=100000)
    history(service, [-10, -10, -10])
    p = plan(service, minutes=20, split_order=True)
    _, result = check(client, plan_id=p)
    assert item(result, "revenge")["status"] == "exempt"
    late = plan(service, minutes=1, split_order=True)
    _, result = check(client, plan_id=late)
    assert item(result, "revenge")["status"] == "hit"


def test_overtrade_split_group_and_plan_budget(service):
    client = quotes(service, current=100000)
    p = plan(service, split_order=True, max_amount_won=500000)
    for i in range(4):
        body, result = check(client, plan_id=p)
        assert send(client, body, result, key=f"group-{i}").json()["status"] == "accepted"
    _, result = check(client, plan_id=p)
    assert item(result, "plan")["status"] == "hit"  # fifth 103000 exceeds cumulative budget
    assert item(result, "overtrading")["status"] == "clear"  # old four count as one valid group
    for i in range(3):
        body, result = check(client)
        assert send(client, body, result, key=f"normal-{i}").json()["status"] == "accepted"
    _, result = check(client)
    assert item(result, "overtrading")["status"] == "hit"


def test_unknown_history_and_legacy_plan(service):
    client, sessions, uid, _ = service
    client.get("/v1/watchlist")
    p = plan(service, entry_min_won=None, entry_max_won=None)
    _, result = check(client, plan_id=p)
    assert item(result, "fomo")["status"] == "unavailable"
    assert item(result, "plan")["status"] == "unavailable"
    assert result["analysis"]["behavior"]["partial"]
    _, result = check(client)
    assert item(result, "plan")["status"] == "unregistered"


def test_warning_confirmation_and_audit(service):
    client = quotes(service)
    body, result = check(client)
    assert result["analysis"]["behavior"]["requires_ack"]
    assert send(client, body, result).json()["status"] == "rejected"
    body, result = check(client)
    response = send(
        client, body, result, key="ack", warning_acknowledged=True, trade_reason="계획 확인 후 진행"
    )
    assert response.json()["status"] == "accepted"
    audit = client.get(f"/v1/orders/{response.json()['order_id']}/analysis").json()
    assert audit["preflight"]["behavior"]["score"] == 30
    assert audit["trade_reason"] == "계획 확인 후 진행"
    assert (
        send(
            client,
            body,
            result,
            key="ack",
            warning_acknowledged=True,
            trade_reason="계획 확인 후 진행",
        ).json()
        == response.json()
    )


def test_high_confirmation_and_new_warning_recheck(service):
    client = quotes(service)
    history(service, [-1, -1, -1])
    p = plan(service, max_amount_won=1000)
    body, result = check(client, plan_id=p)
    assert result["analysis"]["behavior"]["score"] == 75
    assert (
        send(client, body, result, warning_acknowledged=True, trade_reason="재검토 완료").json()[
            "status"
        ]
        == "rejected"
    )
    body, result = check(client, plan_id=p)
    assert (
        send(
            client,
            body,
            result,
            key="high",
            warning_acknowledged=True,
            high_risk_acknowledged=True,
            trade_reason="재검토 완료",
        ).json()["status"]
        == "accepted"
    )
    # A clean preflight cannot authorize a newly detected warning.
    client = quotes(service, current=100000)
    body, result = check(client)
    quotes(service, current=104000)
    response = send(
        client,
        body,
        result,
        key="changed",
        warning_acknowledged=True,
        high_risk_acknowledged=True,
        trade_reason="확인 완료",
    )
    assert response.json()["status"] == "rejected"
    assert "새로운 행동 경고" in response.json()["reason"]


def test_daily_loss_blocks_only_buys_and_cannot_pilot_off_bypass(service):
    client = quotes(service, current=100000)
    history(service, [-1000000])
    _, result = check(client, pilot_enabled=False)
    assert not result["allowed"]
    assert result["analysis"]["behavior"]["level"] == "disabled"
    _, result = check(client, side="sell")
    assert result["allowed"]


def test_loss_day_boundary_korea(service, monkeypatch):
    from app.services import risk

    client = quotes(service, current=100000)
    fixed = datetime(2026, 10, 18, 15, 1, tzinfo=UTC)  # Oct 19 00:01 KST
    monkeypatch.setattr(risk, "now", lambda: fixed)
    history(service, [-1000000])
    _, sessions, uid, _ = service
    with sessions.begin() as db:
        f = db.scalar(select(Fill).where(Fill.user_id == uid))
        f.created_at = fixed - timedelta(minutes=2)
    _, result = check(client)
    assert result["analysis"]["risk"]["daily_pnl_won"] == "0"
    with sessions.begin() as db:
        f = db.scalar(select(Fill).where(Fill.user_id == uid))
        f.created_at = fixed - timedelta(seconds=30)
    _, result = check(client)
    assert result["analysis"]["risk"]["daily_pnl_won"] == "-1000000"


def test_final_risk_recheck_and_pause(service):
    client = quotes(service, current=100000)
    body, result = check(client)
    _, sessions, uid, _ = service
    with sessions.begin() as db:
        db.get(User, uid).trading_paused = True
    assert send(client, body, result).json()["status"] == "rejected"
    # A legacy client omitting the new flag must not silently resume trading.
    prefs = client.get("/v1/settings").json()
    prefs.pop("trading_paused")
    assert client.put("/v1/settings", json=prefs).json()["trading_paused"]


def test_concurrent_cooldown_and_cancel_do_not_bypass(service):
    client = quotes(service, current=100000)
    _, sessions, uid, _ = service
    with sessions.begin() as db:
        db.get(User, uid).cooldown_seconds = 300
    pending = [check(client), check(client)]

    def submit(i):
        return send(client, *pending[i], key=f"cooldown-{i}").json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [0, 1]))
    assert sorted(r["status"] for r in results) == ["accepted", "rejected"]
    accepted = next(r for r in results if r["status"] == "accepted")
    client.post(f"/v1/orders/{accepted['order_id']}/cancel")
    _, result = check(client, pilot_enabled=False)
    assert not result["allowed"]


def test_planned_stop_sell_cooldown_exception(service):
    client = quotes(service, current=97000)
    p = plan(service, side="sell", stop_loss_won=98000)
    _, sessions, uid, _ = service
    with sessions.begin() as db:
        db.get(User, uid).cooldown_seconds = 300
    body, result = check(client, side="sell", plan_id=p)
    assert send(client, body, result).json()["status"] == "accepted"
    _, result = check(client, side="sell", plan_id=p)
    assert result["allowed"]
    _, result = check(client, side="sell")
    assert not result["allowed"]
