"""Official-schema transport fixtures only; these are not live market observations."""

import asyncio
import json
import stat
import time
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import create_app
from app.brokers import namuh
from app.brokers.contracts import MarketQuote, accepts_source
from app.brokers.factory import execution_provider, market_data_provider
from app.brokers.namuh import (
    MarketSession,
    NamuhMarketData,
    NamuhToken,
    NamuhUnavailable,
    market_session,
    parse_trade,
)
from app.config import Settings
from app.models import Fill, Quote, now
from app.schemas import Draft, Submit
from app.services import orders, portfolio
from app.services.market import publish_quote, snapshot


def config(tmp_path, **kwargs):
    return Settings(
        database_url="postgresql://unused",
        market_data_mode="namuh",
        nhplug_token_cache_dir=tmp_path,
        _env_file=None,
        **kwargs,
    )


def session_response(day="20261109"):
    return {
        "rsp_cd": "10000",
        "rsp_msg": "정상적으로 조회가 완료되었습니다.",
        "Output_0": {"bsop_date": day, "start_time": "090000", "cncc_aspr_sta_hour": "152000"},
    }


def push(clock="10:00:00", price="72800", volume="100"):
    return {
        "header": {"tr_cd": "oc", "tr_key": "005930"},
        "body": {"code": "005930", "time": clock, "price": price, "volume": volume},
    }


def test_business_day_anchor_and_stale_rejection():
    at = datetime(2026, 11, 9, 1, tzinfo=UTC)
    sessions = {"005930": market_session(session_response())}
    quote, volume = parse_trade(push(), sessions, at)[0]
    assert quote.as_of == at and quote.source == "namuh_krx" and volume == 100
    # Yesterday's snapshot at the same clock time must not masquerade as fresh today.
    previous = {"005930": MarketSession(date(2026, 11, 6), "090000", "152000")}
    assert parse_trade(push(), previous, at) == []
    for data in [push("09:59:44"), push("10:00:03"), push(price="NaN"), push(volume="1.2")]:
        with pytest.raises(ValueError):
            parse_trade(data, sessions, at)
    assert parse_trade(push("15:20:00"), sessions, at.replace(hour=6, minute=20)) == []
    # An exchange-supplied delayed opening is respected.
    sessions["005930"] = MarketSession(date(2026, 11, 9), "100000", "162000")
    assert parse_trade(push("09:59:59"), sessions, at) == []


def test_bad_session_and_wrong_channel_fail_closed():
    for patch in [{"rsp_msg": "조회 실패"}, {"Output_0": {}}, {"rsp_msg": ""}]:
        with pytest.raises(NamuhUnavailable):
            market_session({**session_response(), **patch})
    data = push()
    data["header"]["tr_cd"] = "d2"  # account execution notice is never a quote
    with pytest.raises(ValueError):
        parse_trade(data, {}, datetime.now(UTC))


def test_token_cache_reused_across_instances_with_private_permissions(tmp_path, monkeypatch):
    settings = config(tmp_path, nhplug_app_key="fixture-key", nhplug_app_secret="fixture-secret")
    calls = []

    def post(path, **kwargs):
        calls.append(path)
        assert kwargs["query"]["scope"] == "oob"
        return 200, {"access_token": "fixture-token", "expires_in": 86400}

    monkeypatch.setattr(namuh, "_post", post)
    tokens = NamuhToken(settings)
    assert tokens.get() == "fixture-token"
    assert NamuhToken(settings).get() == "fixture-token"
    assert calls == ["/oauth2/token"]
    assert stat.S_IMODE(tokens.path.stat().st_mode) == 0o600
    tokens.invalidate()
    assert tokens.get() == "fixture-token" and len(calls) == 2


def test_rate_limit_never_forces_reissue(tmp_path, monkeypatch):
    settings = config(tmp_path, nhplug_app_key="fixture", nhplug_app_secret="fixture")
    feed = NamuhMarketData(settings)
    namuh._write_private(feed.tokens.path, {"token": "cached", "expires_at": time.time() + 3600})
    monkeypatch.setattr(namuh, "_post", lambda *a, **kw: (429, {}))
    with pytest.raises(NamuhUnavailable):
        feed.load_session("cached", "005930")
    assert feed.tokens.get() == "cached"
    monkeypatch.setattr(namuh, "_post", lambda *a, **kw: (401, {}))
    with pytest.raises(NamuhUnavailable):
        feed.load_session("cached", "005930")
    assert not feed.tokens.path.exists()


def test_no_keys_and_no_order_transport(tmp_path):
    feed = market_data_provider(config(tmp_path))
    asyncio.run(feed.run())
    assert feed.status()["state"] == "waiting_credentials"
    with pytest.raises(ValueError):
        namuh._post("/krstock/order/v1/cashBuy", body={})
    assert type(execution_provider()).__name__ == "BrokerAdapterTemplate"


def test_ack_subscription_and_unsubscribe(tmp_path, monkeypatch):
    import websockets.asyncio.client

    settings = config(tmp_path, nhplug_app_key="fixture", nhplug_app_secret="fixture")
    feed = NamuhMarketData(settings)
    feed.tokens.expiry = time.time() + 3600
    monkeypatch.setattr(feed.tokens, "get", lambda: "fixture-token")
    monkeypatch.setattr(feed, "load_session", lambda *args: market_session(session_response()))
    monkeypatch.setattr(namuh, "tls_context", lambda: None)
    sent = []

    class Socket:
        count = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def send(self, raw):
            sent.append(json.loads(raw))

        async def recv(self):
            self.count += 1
            if self.count == 1:
                return json.dumps(
                    {
                        "header": {"tr_cd": "oc", "tr_type": "1", "rsp_cd": "00000"},
                        "body": {"tr_key": settings.nhplug_symbols},
                    }
                )
            assert feed.state == "subscribed"
            raise asyncio.CancelledError

    def connect(url, **kwargs):
        assert url == "wss://api.nhplug.com:7070/websocket"
        return Socket()

    monkeypatch.setattr(websockets.asyncio.client, "connect", connect)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(feed.run())
    assert [message["header"]["tr_type"] for message in sent] == ["1", "1", "2", "2"]
    assert all(message["body"]["tr_cd"] == "oc" for message in sent)
    assert feed.state == "stopped"


def test_namuh_paper_order_feedback_fill_and_source_isolation(service):
    _, sessions, user_id, settings = service
    settings.market_data_mode = "namuh"
    feed = NamuhMarketData(settings)
    draft = Draft(
        symbol="005930",
        side="buy",
        quantity=1,
        limit_price_won="72800",
        order_type="limit",
        pilot_enabled=True,
    )
    assert not accepts_source("kis_krx", settings) and not accepts_source("demo", settings)
    with sessions.begin() as db:
        publish_quote(db, MarketQuote("005930", 72800, now(), "kis_krx"))
    with sessions.begin() as db:
        assert snapshot(db, user_id, feed) == []
        assert not orders.preflight(db, user_id, draft, settings).allowed
    with sessions.begin() as db:
        publish_quote(db, MarketQuote("005930", 72800, now(), "namuh_krx"))
    with sessions.begin() as db:
        assert snapshot(db, user_id, feed)[0].source == "namuh_krx"
        check = orders.preflight(db, user_id, draft, settings)
        assert check.allowed and check.analysis
        request = Submit(
            **draft.model_dump(),
            check_id=check.check_id,
            warning_acknowledged=True,
            high_risk_acknowledged=True,
            trade_reason="계획에 따른 모의 주문",
        )
        receipt = orders.submit(db, user_id, request, "namuh-paper", settings)
    with sessions.begin() as db:
        publish_quote(db, MarketQuote("005930", 72000, now(), "namuh_krx"))
    with sessions.begin() as db:
        portfolio.settle(db, user_id, settings)
        fill = db.scalar(select(Fill).where(Fill.order_id == receipt.order_id))
        assert fill.source == "namuh_krx" and fill.price_won == 72000
        db.get(Quote, "005930").as_of = now() - timedelta(seconds=30)
    with sessions.begin() as db:
        assert not orders.preflight(db, user_id, draft, settings).allowed


def test_namuh_app_boots_without_keys_and_reports_paper_only(database):
    url, sessions = database
    settings = Settings(
        database_url=url, market_data_mode="namuh", paper_worker_enabled=False, _env_file=None
    )
    with TestClient(create_app(settings, sessions)) as client:
        response = client.post(
            "/v1/auth/signup",
            json={
                "email": "namuh-fixture@example.com",
                "password": "test-password-123",
                "password_confirmation": "test-password-123",
            },
        )
        assert response.status_code == 201
        login = client.post(
            "/v1/auth/login",
            json={"email": "namuh-fixture@example.com", "password": "test-password-123"},
        )
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        status = client.get("/v1/system/status").json()
        assert status["market_data_mode"] == "namuh"
        assert status["mode"] == "paper" and not status["real_broker_configured"]
        assert status["market_feed"]["state"] == "waiting_credentials"


def test_rejected_key_stops_retry_and_hides_credentials(tmp_path, monkeypatch):
    settings = config(tmp_path, nhplug_app_key="secret-key-value", nhplug_app_secret="secret-value")
    calls = []

    def rejected(*args, **kwargs):
        calls.append(1)
        return 403, {"error_code": "IGW40031"}

    monkeypatch.setattr(namuh, "_post", rejected)
    feed = NamuhMarketData(settings)
    asyncio.run(feed.run())
    status = feed.status()
    assert status["state"] == "auth_failed" and len(calls) == 1
    assert "IGW40031" in status["last_error"]
    assert "secret-key-value" not in json.dumps(status)
    assert "secret-value" not in json.dumps(status)


def test_token_wire_protocol_and_error_body_redaction(tmp_path, monkeypatch):
    settings = config(tmp_path, nhplug_app_key="fixture-key", nhplug_app_secret="fixture-secret")
    seen = []

    class Response:
        status = 403

        def read(self, size):
            return b'{"error":"IGW40031", "secret":"must-not-escape"}'

    class Connection:
        def __init__(self, host, port, **kwargs):
            assert (host, port) == ("api.nhplug.com", 8443)

        def request(self, method, path, body, headers):
            from urllib.parse import parse_qs, urlsplit

            assert method == "POST"
            url = urlsplit(path)
            assert url.path == "/oauth2/token"
            assert parse_qs(url.query) == {
                "appkey": ["fixture-key"],
                "appsecretkey": ["fixture-secret"],
                "grant_type": ["client_credentials"],
                "scope": ["oob"],
            }
            assert headers["Content-Type"] == "application/x-www-form-urlencoded"
            seen.append(1)

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(namuh.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(namuh, "tls_context", lambda: None)
    with pytest.raises(namuh.NamuhAuthRejected) as error:
        NamuhToken(settings).get()
    assert len(seen) == 1 and "IGW40031" in str(error.value)
    assert "must-not-escape" not in str(error.value) and "fixture-key" not in str(error.value)
