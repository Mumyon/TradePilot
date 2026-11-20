from datetime import UTC, datetime, timedelta
from time import monotonic

from fastapi.testclient import TestClient

from app import api
from app.brokers.contracts import MarketQuote
from app.brokers.toss import TossMarketData
from app.cli import create_user
from app.config import Settings
from app.models import Symbol
from app.services.candles import aggregate_chart_candles
from app.services.volatility_index import parse_closes


def test_cached_discovery_ranking_picks_up_daily_candle_when_it_arrives():
    provider = TossMarketData(Settings(database_url="postgresql://unused", _env_file=None))
    provider._snapshot = {"items": [{"symbol": "005930"}, {"symbol": "000660"}]}
    provider._snapshot_at = monotonic()

    first = provider.discovery_snapshot()
    assert first["items"][0]["candle"] is None
    candle = dict(open_won=100, high_won=125, low_won=95, close_won=120)
    provider._discovery_candles["005930"] = candle
    items = provider.discovery_snapshot()["items"]
    assert items[0]["candle"] == candle
    assert items[1]["candle"] is None
    assert first["items"][0]["candle"] is None


def test_chart_aggregates_only_closed_complete_buckets():
    at = datetime(2026, 11, 12, 0, 6, tzinfo=UTC)
    rows = [
        dict(
            opened_at=at.replace(minute=i),
            open_won=100 + i,
            high_won=110 + i,
            low_won=95 + i,
            close_won=105 + i,
            volume=10,
            source="toss_kr",
        )
        for i in (0, 1, 2, 3, 5, 6, 7, 8)
    ]
    [bar] = aggregate_chart_candles(rows, "3m", at)
    assert (bar["open_won"], bar["high_won"], bar["low_won"], bar["close_won"]) == (
        100,
        112,
        95,
        107,
    )
    assert bar["volume"] == 30
    assert bar["closed_at"] == at.replace(minute=3)
    closed, partial = aggregate_chart_candles(rows, "3m", at, include_current=True)
    assert closed == bar
    assert partial["opened_at"] == at
    assert partial["complete"] is False
    assert partial["close_won"] == 111


def test_vix_uses_latest_valid_published_close():
    today = datetime(2026, 11, 12).date()
    csv = "DATE,CLOSE\n11/12/2026,18.7\n11/10/2026,17\n11/11/2026,17.49\n11/13/2026,99\n"
    assert parse_closes(csv, today) == {"as_of": "2026-11-12", "close": 18.7, "change": 1.21}


def test_previous_close_uses_ranking_base_price_without_chart_request():
    provider = TossMarketData(Settings(database_url="postgresql://unused", _env_file=None))
    provider._snapshot = {"checked_at": datetime.now(UTC)}
    provider._rank_rows = [{"symbol": "005930", "previous_close_won": 188700}]
    assert provider.get_previous_close("005930") == 188700


def test_previous_close_excludes_today_and_caches_daily_result(monkeypatch):
    provider = TossMarketData(Settings(database_url="postgresql://unused", _env_file=None))
    stamp = datetime.now(UTC)
    calls = []

    def candles(symbol, interval):
        calls.append((symbol, interval))
        return [
            {"opened_at": stamp - timedelta(days=1), "close_won": 188700},
            {"opened_at": stamp, "close_won": 190000},
        ]

    monkeypatch.setattr(provider, "get_candles", candles)
    assert provider.get_previous_close("005930") == 188700
    assert provider.get_previous_close("005930") == 188700
    assert calls == [("005930", "1d")]


def test_chart_socket_relays_ticks_for_a_symbol_outside_watchlist(database, monkeypatch):
    url, sessions = database
    settings = Settings(
        database_url=url, market_data_mode="toss", paper_worker_enabled=False, _env_file=None
    )
    provider = TossMarketData(settings)
    with sessions.begin() as db:
        db.add(Symbol(symbol="035420", name="NAVER"))
        create_user(db, "chart@example.com", "chart-password-123", demo_holdings=False)
    monkeypatch.setattr(api, "market_data_provider", lambda _: provider)
    with TestClient(api.create_app(settings, sessions)) as client:
        login = client.post(
            "/v1/auth/login", json={"email": "chart@example.com", "password": "chart-password-123"}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        ticket = client.post("/v1/ws-ticket", headers=headers).json()["ticket"]
        with client.websocket_connect(f"/v1/ws?ticket={ticket}") as ws:
            ws.send_json({"type": "chart_symbol", "symbol": "035420"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert "035420" in provider.subscription_symbols()
            at = datetime.now(UTC)
            client.portal.call(provider.accept_trade, MarketQuote("035420", 120000, at, "toss_kr"))
            event = ws.receive_json()
            assert event["type"] == "chart_quote"
            assert event["data"]["name"] == "NAVER"
            assert event["data"]["price_won"] == "120000"
            assert datetime.fromisoformat(event["data"]["as_of"]) == at
            selected = client.get("/v1/market/035420/quote", headers=headers).json()
            assert selected["execution_quote"] == event["data"]
            ws.send_json({"type": "chart_symbol", "symbol": None})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert "035420" not in provider.subscription_symbols()
