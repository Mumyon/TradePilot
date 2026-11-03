from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select

from app.models import Automation, AutomationEvent, Candle, Holding, Order, Quote, User, now
from app.services import automation
from app.services.portfolio import settle


class NoCandles:
    def get_candles(self, symbol, interval):
        return []


@pytest.fixture
def running(service):
    client, sessions, user_id, settings = service
    settings.paper_worker_enabled = True
    with sessions.begin() as db:
        db.execute(delete(Holding).where(Holding.user_id == user_id))
    sid = client.post(
        "/v1/strategies", json=dict(name="auto", symbol="005930", fast_period=2, slow_period=3)
    ).json()["id"]
    result = client.put(
        f"/v1/strategies/{sid}/automation", json=dict(enabled=True, budget_won=500000)
    )
    assert result.status_code == 200, result.text
    aid = result.json()["id"]
    stamp = now().replace(second=0, microsecond=0) - timedelta(minutes=6)
    with sessions.begin() as db:
        for i, price in enumerate([72800, 72850, 72900]):
            db.add(
                Candle(
                    symbol="005930",
                    interval="5m",
                    source="demo",
                    opened_at=stamp - timedelta(minutes=(2 - i) * 5),
                    open_won=price,
                    close_won=price,
                    low_won=price,
                    high_won=price,
                    volume=1000,
                    complete=True,
                )
            )
        db.merge(Quote(symbol="005930", source="demo", price_won=72900, as_of=now(), sequence=1))
    return client, sessions, user_id, settings, sid, aid


def process(running):
    _, sessions, _, settings, _, aid = running
    with sessions.begin() as db:
        automation.process(db, aid, NoCandles(), settings)


def test_duplicate_workers_and_stop_release_reservations(running):
    client, sessions, user, _, sid, aid = running
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: process(running), range(2)))
    with sessions() as db:
        assert db.scalar(select(func.count(Order.id))) == 1
        assert db.scalar(select(func.count(AutomationEvent.id))) == 1
        assert db.get(User, user).reserved_won > 0
        assert db.scalar(select(Order)).status == "accepted"
    response = client.put(f"/v1/strategies/{sid}/automation", json={"enabled": False})
    assert response.status_code == 200
    with sessions() as db:
        assert db.get(User, user).reserved_won == 0
        assert db.scalar(select(Order)).status == "cancelled"
        assert not db.get(Automation, aid).enabled
    process(running)
    assert (
        client.get(f"/v1/automations/{aid}/events").json()["items"][0]["order_status"]
        == "cancelled"
    )


def test_fill_then_stop_preserves_holding(running):
    client, sessions, user, settings, sid, _ = running
    process(running)
    with sessions.begin() as db:
        db.get(Quote, "005930").as_of = now()
        settle(db, user, settings)
    client.put(f"/v1/strategies/{sid}/automation", json={"enabled": False})
    with sessions() as db:
        assert db.get(Holding, (user, "005930")).quantity == 6
        assert db.scalar(select(Order)).status == "filled"
        assert db.get(User, user).reserved_won == 0


def test_global_pause_cancels_before_fill(running):
    _, sessions, user, settings, _, aid = running
    process(running)
    settings.orders_halted = True
    process(running)
    with sessions() as db:
        assert not db.get(Automation, aid).enabled
        assert db.scalar(select(Order)).status == "cancelled"
        assert db.get(User, user).reserved_won == 0


def test_behavior_warning_is_not_auto_acknowledged(running, monkeypatch):
    from app.services import risk

    original = risk.evaluate

    def warning(*args, **kwargs):
        result = original(*args, **kwargs)
        result["behavior"]["requires_ack"] = True
        return result

    monkeypatch.setattr(risk, "evaluate", warning)
    process(running)
    with running[1]() as db:
        assert db.scalar(select(func.count(Order.id))) == 0
        assert "위험/행동" in db.scalar(select(AutomationEvent)).message


def test_risk_limit_blocks_order(running):
    with running[1].begin() as db:
        db.get(User, running[2]).order_limit_won = 10000
    process(running)
    with running[1]() as db:
        assert db.scalar(select(func.count(Order.id))) == 0
        assert "주문한도" in db.scalar(select(AutomationEvent)).message


def test_manual_intervention_stops(running):
    _, sessions, user, _, _, aid = running
    with sessions.begin() as db:
        db.add(
            Order(
                user_id=user,
                idempotency_key="manual",
                request_body={},
                symbol="005930",
                side="buy",
                quantity=1,
                limit_price_won=72900,
                status="cancelled",
                analysis={},
            )
        )
    process(running)
    with sessions() as db:
        assert not db.get(Automation, aid).enabled
        assert "수동" in db.get(Automation, aid).message
        assert db.scalar(select(func.count(AutomationEvent.id))) == 0


def test_snapshot_frozen_and_conflicting_run_rejected(running):
    client, _, _, _, sid, _ = running
    body = dict(name="changed", symbol="005930", fast_period=2, slow_period=4)
    client.put("/v1/strategies/" + sid, json=body)
    assert client.put(f"/v1/strategies/{sid}/automation", json={"enabled": True}).status_code == 409
    new = client.post("/v1/strategies", json=body).json()["id"]
    assert client.put(f"/v1/strategies/{new}/automation", json={"enabled": True}).status_code == 409
    assert client.get("/v1/automations").json()["items"][0]["strategy_snapshot"]["slow_period"] == 3


def test_disabled_market_and_existing_holding_rejected(service):
    client, _, _, settings = service
    sid = client.post("/v1/strategies", json=dict(name="test", symbol="005930")).json()["id"]
    assert client.put(f"/v1/strategies/{sid}/automation", json={"enabled": True}).status_code == 409
    settings.paper_worker_enabled = True
    assert client.put(f"/v1/strategies/{sid}/automation", json={"enabled": True}).status_code == 409


def test_stale_data_and_transaction_rollback(running):
    _, sessions, user, settings, _, aid = running
    with pytest.raises(RuntimeError):
        with sessions.begin() as db:
            automation.process(db, aid, NoCandles(), settings)
            raise RuntimeError("simulate commit failure")
    with sessions() as db:
        assert db.get(Automation, aid).last_bar is None
        assert db.scalar(select(func.count(Order.id))) == 0
        assert db.get(User, user).reserved_won == 0
    with sessions.begin() as db:
        db.get(Quote, "005930").as_of = now() - timedelta(minutes=1)
    process(running)
    with sessions() as db:
        assert db.scalar(select(func.count(Order.id))) == 0
        assert "최신 합성" in db.scalar(select(AutomationEvent)).message


def test_other_user_cannot_control_or_read(running):
    client, _, _, _, sid, aid = running
    body = dict(
        email="auto-other@example.com",
        password="other-password-123",
        password_confirmation="other-password-123",
    )
    assert client.post("/v1/auth/signup", json=body).status_code == 201
    token = client.post("/v1/auth/login", json=body).json()["access_token"]
    client.headers["Authorization"] = "Bearer " + token
    assert client.get("/v1/automations").json()["items"] == []
    assert client.get(f"/v1/automations/{aid}/events").status_code == 404
    assert (
        client.put(f"/v1/strategies/{sid}/automation", json={"enabled": False}).status_code == 404
    )


def test_buy_sell_cycle_uses_existing_paper_settlement(running):
    _, sessions, user, settings, _, aid = running
    process(running)
    with sessions.begin() as db:
        db.get(Quote, "005930").as_of = now()
        settle(db, user, settings)
        latest = db.get(Automation, aid).last_bar + timedelta(seconds=30)
        db.execute(delete(Candle))
        for i, price in enumerate([73100, 73050, 73000]):
            db.add(
                Candle(
                    symbol="005930",
                    interval="5m",
                    source="demo",
                    opened_at=latest - timedelta(minutes=(2 - i) * 5),
                    open_won=price,
                    close_won=price,
                    low_won=price,
                    high_won=price,
                    volume=1000,
                    complete=True,
                )
            )
        quote = db.get(Quote, "005930")
        quote.price_won = 73000
        quote.as_of = now()
    process(running)
    with sessions.begin() as db:
        assert db.scalar(select(Order).where(Order.side == "sell")).status == "accepted"
        db.get(Quote, "005930").as_of = now()
        settle(db, user, settings)
    with sessions() as db:
        assert db.get(Holding, (user, "005930")).quantity == 0
        assert db.get(User, user).cash_won > 10_000_000
        assert len(db.scalars(select(Order).where(Order.status == "filled")).all()) == 2


def test_strategy_disable_cancels_immediately(running):
    client, sessions, user, _, sid, aid = running
    process(running)
    response = client.put(
        "/v1/strategies/" + sid,
        json=dict(name="auto", symbol="005930", fast_period=2, slow_period=3, enabled=False),
    )
    assert response.status_code == 200
    with sessions() as db:
        assert not db.get(Automation, aid).enabled
        assert db.scalar(select(Order)).status == "cancelled"
        assert db.get(User, user).reserved_won == 0
