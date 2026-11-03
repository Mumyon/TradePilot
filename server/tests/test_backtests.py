from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import Holding, Order, User
from app.schemas import BacktestRequest
from app.services.backtests import simulate


def request(**kw):
    return BacktestRequest(
        source="demo",
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 2, 1, tzinfo=UTC),
        **kw,
    )


def bars(values):
    return [
        dict(
            opened_at=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(minutes=5 * i),
            open_won=p,
            close_won=p,
            high_won=p,
            low_won=p,
            volume=1000,
        )
        for i, p in enumerate(values)
    ]


CONFIG = dict(name="test", symbol="005930", fast_period=2, slow_period=3, enabled=True)


def test_next_open_costs_and_accounting():
    result = simulate(
        bars([100, 110, 120, 130, 100, 90, 80]),
        CONFIG,
        request(initial_cash_won=10000, fee_bps=2, slippage_bps=5),
    )
    buy, sell = result["trades"]
    assert buy["at"].endswith("00:15:00+00:00")
    assert buy["price_won"] == 131  # adverse rounding, not signal-bar close 120
    assert sell["at"].endswith("00:25:00+00:00")
    assert sell["price_won"] == 89
    assert result["cash_won"] >= 0
    assert result["final_equity_won"] == 10000 + result["realized_pnl_won"]
    assert result["fee_won"] == buy["fee_won"] + sell["fee_won"]
    assert result["losses"] == 1 and result["win_rate_pct"] == 0
    assert result["max_drawdown_pct"] > 0


def test_future_mutation_cannot_change_prior_trades():
    original = bars([100, 110, 120, 130, 140, 150, 160])
    altered = bars([100, 110, 120, 130, 140, 10, 10])
    a = simulate(original, CONFIG, request())
    b = simulate(altered, CONFIG, request())
    assert a["trades"][0] == b["trades"][0]
    assert a["equity_curve"][:5] == b["equity_curve"][:5]
    assert a["dataset_sha256"] != b["dataset_sha256"]


def test_gap_does_not_fill_stale_signal():
    data = bars([100, 110, 120, 130, 140, 150])
    for r in data[3:]:
        r["opened_at"] += timedelta(hours=1)
    result = simulate(data, CONFIG, request())
    assert result["trades"] == []
    assert result["win_rate_pct"] is None


def test_flat_and_open_position():
    assert simulate(bars([100] * 10), CONFIG, request())["return_pct"] == 0
    r = simulate(bars([100, 110, 120, 130, 140]), CONFIG, request())
    assert r["open_quantity"] > 0 and r["round_trips"] == 0
    assert r["final_equity_won"] - r["initial_cash_won"] == r["unrealized_pnl_won"]


def test_strategy_backtest_persistence_and_isolation(service):
    client, sessions, user_id, _ = service
    config = {**CONFIG, "slow_period": 20, "fast_period": 5}
    created = client.post("/v1/strategies", json=config)
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    with sessions() as db:
        before = (
            db.get(User, user_id).cash_won,
            db.scalar(select(func.count(Order.id))),
            [(h.symbol, h.quantity) for h in db.scalars(select(Holding))],
        )
    end = datetime.now(UTC) + timedelta(minutes=1)
    body = dict(source="demo", start=(end - timedelta(days=1)).isoformat(), end=end.isoformat())
    result = client.post(f"/v1/strategies/{sid}/backtests", json=body)
    assert result.status_code == 201, result.text
    data = result.json()
    assert data["data_label"] == "합성 시연 데이터"
    assert client.get("/v1/backtests").json()["items"][0]["id"] == data["id"]
    assert client.get("/v1/backtests/" + data["id"]).json()["trades"] == data["trades"]
    assert client.put("/v1/strategies/" + sid, json={**config, "enabled": False}).status_code == 200
    assert client.post(f"/v1/strategies/{sid}/backtests", json=body).status_code == 409
    assert client.get("/v1/backtests/" + data["id"]).json()["strategy_snapshot"]["enabled"] is True
    with sessions() as db:
        after = (
            db.get(User, user_id).cash_won,
            db.scalar(select(func.count(Order.id))),
            [(h.symbol, h.quantity) for h in db.scalars(select(Holding))],
        )
    assert before == after
    client.post(
        "/v1/auth/signup",
        json={
            "email": "other@example.com",
            "password": "other-password-123",
            "password_confirmation": "other-password-123",
        },
    )
    login = client.post(
        "/v1/auth/login", json={"email": "other@example.com", "password": "other-password-123"}
    )
    client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
    assert client.get("/v1/strategies").json()["items"] == []
    assert client.get("/v1/backtests/" + data["id"]).status_code == 404
    assert client.post(f"/v1/strategies/{sid}/backtests", json=body).status_code == 404


def test_invalid_config_and_missing_data(service):
    client, *_ = service
    assert client.post("/v1/strategies", json={**CONFIG, "fast_period": 30}).status_code == 422
    sid = client.post("/v1/strategies", json=CONFIG).json()["id"]
    body = request().model_dump(mode="json")
    body["source"] = "missing-csv"
    assert client.post(f"/v1/strategies/{sid}/backtests", json=body).status_code == 422
    body["end"] = body["start"]
    assert client.post(f"/v1/strategies/{sid}/backtests", json=body).status_code == 422
