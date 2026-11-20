"""Opt-in live feed validation in a disposable DB schema. Never broker orders."""

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.cli import create_user
from app.config import Settings

pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_TOSS") != "1", reason="live opt-in required")


def wait_until(fetch, ready, seconds=40):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        last = fetch()
        if ready(last):
            return last
        time.sleep(1)
    pytest.fail(f"Live paper condition did not complete: {last}")


def test_real_toss_feed_paper_buy_sell_cancel_journal(database):
    url, sessions = database
    settings = Settings(
        database_url=url,
        market_data_mode="toss",
        paper_worker_enabled=True,
        ai_review_enabled=False,
        _env_file=Path(__file__).resolve().parents[1] / ".env",
    )
    if not settings.toss_client_id or not settings.toss_client_secret:
        pytest.skip("Local Toss credentials required")
    with sessions.begin() as db:
        create_user(db, "isolated-paper-check@example.com", "isolated-test-password")
    app = create_app(settings, sessions)
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/login",
            json={
                "email": "isolated-paper-check@example.com",
                "password": "isolated-test-password",
            },
        )
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        wait_until(
            lambda: client.get("/v1/account").json(), lambda a: a["market_session"]["can_trade"]
        )
        quotes = wait_until(
            lambda: client.get("/v1/watchlist").json()["items"],
            lambda rows: any(q["symbol"] == "005930" for q in rows),
        )
        quote = next(q for q in quotes if q["symbol"] == "005930")
        assert quote["source"] == "toss_kr"
        current = int(quote["price_won"])

        def submit(key, side, price):
            draft = dict(
                symbol="005930",
                side=side,
                quantity=1,
                limit_price_won=str(price),
                order_type="limit",
                pilot_enabled=False,
            )
            checked = client.post("/v1/orders/check", json=draft).json()
            assert checked["allowed"], checked["messages"]
            response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": key},
                json={
                    **draft,
                    "check_id": checked["check_id"],
                    "trade_reason": "실시간 모의 검증",
                    "warning_acknowledged": True,
                    "high_risk_acknowledged": True,
                },
            ).json()
            assert response["status"] == "accepted", response
            return response["order_id"]

        buy = submit("live-buy", "buy", current * 105 // 100)
        wait_until(
            lambda: client.get("/v1/orders").json()["items"],
            lambda rows: any(r["order_id"] == buy and r["status"] == "filled" for r in rows),
        )
        sell = submit("live-sell", "sell", current * 95 // 100)
        wait_until(
            lambda: client.get("/v1/orders").json()["items"],
            lambda rows: any(r["order_id"] == sell and r["status"] == "filled" for r in rows),
        )
        cancelled = submit("live-cancel", "buy", 100)
        assert client.post(f"/v1/orders/{cancelled}/cancel").json()["status"] == "cancelled"
        fills = client.get("/v1/fills").json()["items"]
        assert len(fills) == 2
        assert all(f["source"] == "toss_kr" and f["quote_as_of"] for f in fills)
        pnl = sum(int(f["realized_pnl_won"] or 0) for f in fills)
        account = client.get("/v1/account").json()
        assert account["reserved_won"] == "0"
        assert int(account["cash_won"]) == 10000000 + pnl
        assert account["holdings"] == []
        records = client.get("/v1/journal").json()["items"]
        assert len(records) == 3
        assert sum(r["fill"] is not None for r in records) == 2
        print(
            "Live Toss paper: buy+sell filled, cancel verified; "
            f"cash={account['cash_won']}, pnl={pnl}, journal=3"
        )
