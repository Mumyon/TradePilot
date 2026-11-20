import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.brokers.contracts import BrokerNotConfigured, MarketQuote
from app.brokers.factory import execution_provider, market_data_provider
from app.brokers.kis import KisMarketData, parse_trades
from app.config import Settings
from app.models import Fill, Order, Quote, now
from app.schemas import Draft, Submit
from app.services import orders, portfolio
from app.services.market import publish_quote


def settings(**kwargs):
    return Settings(
        database_url="postgresql://unused", market_data_mode="kis", _env_file=None, **kwargs
    )


def frame(stamp, price=72800, volume=100, symbol="005930"):
    from app.brokers.kis import KST

    local = stamp.astimezone(KST)
    row = ["0"] * 47
    row[0], row[1], row[2], row[13], row[33] = (
        symbol,
        local.strftime("%H%M%S"),
        str(price),
        str(volume),
        local.strftime("%Y%m%d"),
    )
    return "0|H0STCNT0|001|" + "^".join(row)


def test_exchange_clock_batch_and_validation():
    at = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)
    raw = frame(at)
    quote, volume = parse_trades(raw, at + timedelta(seconds=2))[0]
    assert quote.as_of == at and quote.source == "kis_krx" and volume == 100
    payload = raw.split("|", 3)[3]
    assert len(parse_trades("0|H0STCNT0|002|" + payload + "^" + payload, at)) == 2
    for bad in [raw.replace("H0STCNT0", "H0STCNI0"), frame(at, price=0), raw + "^extra"]:
        with pytest.raises(ValueError):
            parse_trades(bad, at)
    with pytest.raises(ValueError):
        parse_trades(raw, at + timedelta(seconds=16))
    with pytest.raises(ValueError):
        parse_trades(frame(at + timedelta(seconds=3)), at)
    assert parse_trades(frame(at.replace(hour=7)), at.replace(hour=7)) == []


def test_duplicate_reconnect_and_complete_bars():
    feed = KisMarketData(settings())
    at = datetime(2026, 11, 9, 1, 0, 10, tzinfo=UTC)
    feed.reset_connection(at)
    feed.accept(frame(at), at)
    for minute, volume, price in [(1, 110, 72800), (2, 120, 73000), (3, 125, 72900)]:
        stamp = at.replace(minute=minute, second=0)
        feed.accept(frame(stamp, price, volume), stamp)
        feed.accept(frame(stamp, price, volume), stamp)
    rows = feed.get_candles("005930", "1m")
    assert len(rows) == 2 and [r["volume"] for r in rows] == [10, 10]
    assert rows[0]["opened_at"] == at.replace(minute=1, second=0)
    feed.reset_connection(at.replace(minute=3, second=30))
    assert feed.get_quote("005930") is None
    stamp = at.replace(minute=4, second=0)
    feed.accept(frame(stamp, volume=140), stamp)
    assert len(feed.get_candles("005930", "1m")) == 2  # partial 03-minute discarded


def test_missing_keys_does_not_call_network_and_execution_stays_stub():
    feed = market_data_provider(settings())
    asyncio.run(feed.run())
    assert feed.status()["state"] == "waiting_credentials"
    with pytest.raises(BrokerNotConfigured):
        execution_provider().get_balance("not-a-real-account")


def test_live_paper_feedback_fill_and_stale_block(service):
    _, sessions, user_id, config = service
    config.market_data_mode = "kis"
    draft = Draft(
        symbol="005930",
        side="buy",
        quantity=1,
        limit_price_won="72800",
        order_type="limit",
        pilot_enabled=True,
    )
    with sessions.begin() as db:
        publish_quote(db, MarketQuote("005930", 72800, now(), "demo"))
    with sessions.begin() as db:
        assert not orders.preflight(db, user_id, draft, config).allowed
    with sessions.begin() as db:
        publish_quote(db, MarketQuote("005930", 72800, now(), "kis_krx"))
    with sessions.begin() as db:
        check = orders.preflight(db, user_id, draft, config)
        assert check.allowed and check.analysis
        request = Submit(
            **draft.model_dump(),
            check_id=check.check_id,
            warning_acknowledged=True,
            high_risk_acknowledged=True,
            trade_reason="계획에 따른 모의 주문",
        )
        receipt = orders.submit(db, user_id, request, "live-paper", config)
    with sessions.begin() as db:
        portfolio.settle(db, user_id, config)
        assert db.get(Order, receipt.order_id).status == "accepted"
    with sessions.begin() as db:
        publish_quote(db, MarketQuote("005930", 72000, now(), "kis_krx"))
    with sessions.begin() as db:
        portfolio.settle(db, user_id, config)
        fill = db.scalar(select(Fill).where(Fill.order_id == receipt.order_id))
        assert fill.source == "kis_krx" and fill.price_won == 72000
        db.get(Quote, "005930").as_of = now() - timedelta(seconds=30)
    with sessions.begin() as db:
        assert not orders.preflight(db, user_id, draft, config).allowed


def test_same_second_quote_correction_is_idempotent(service):
    _, sessions, _, _ = service
    at = now()
    with sessions.begin() as db:
        for price in [72800, 72900, 72900]:
            publish_quote(db, MarketQuote("005930", price, at, "kis_krx"))
    with sessions() as db:
        q = db.get(Quote, "005930")
        assert q.price_won == 72900 and q.sequence == 2


def test_stream_subscription_heartbeat_and_cancellation(monkeypatch):
    import json

    import websockets.asyncio.client

    feed = KisMarketData(settings(kis_app_key="test-key", kis_app_secret="test-secret"))
    monkeypatch.setattr(feed, "approval", lambda: "test-approval")
    sent, pongs = [], []

    class Socket:
        count = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def send(self, value):
            sent.append(json.loads(value))

        async def pong(self, value):
            pongs.append(value)

        async def recv(self):
            self.count += 1
            if self.count == 1:
                return json.dumps({"header": {"tr_id": "H0STCNT0"}, "body": {"rt_cd": "0"}})
            if self.count == 2:
                return json.dumps({"header": {"tr_id": "PINGPONG"}})
            raise asyncio.CancelledError

    monkeypatch.setattr(websockets.asyncio.client, "connect", lambda *a, **kw: Socket())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(feed.run())
    assert {r["body"]["input"]["tr_key"] for r in sent} == {"005930", "000660"}
    assert all(r["body"]["input"]["tr_id"] == "H0STCNT0" for r in sent)
    assert all(r["header"]["approval_key"] == "test-approval" for r in sent)
    assert len(pongs) == 1 and feed.status()["state"] == "stopped"


def test_worker_persists_observed_bars_once(service):
    from app.models import Candle
    from app.services import paper_worker

    _, sessions, _, config = service
    config.market_data_mode = "kis"
    feed = KisMarketData(config)
    # Recorded synthetic transport fixture, not a real market observation.
    start = datetime(2026, 10, 5, 1, 0, 10, tzinfo=UTC)
    feed.reset_connection(start)
    for minute in range(3):
        at = start + timedelta(minutes=minute)
        feed.accept(frame(at, volume=100 + minute * 10), at)
    paper_worker.tick(sessions, feed, config)
    paper_worker.tick(sessions, feed, config)
    with sessions() as db:
        rows = db.scalars(select(Candle).where(Candle.source == "kis_krx")).all()
        assert len(rows) == 1 and rows[0].volume == 10 and rows[0].complete
