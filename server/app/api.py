import asyncio
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import schemas, security
from .brokers.factory import market_data_provider
from .config import Settings
from .db import make_database
from .models import AuthSession, Order, User, WsTicket
from .services import market, orders, predictions


def create_app(settings: Settings, session_factory=None) -> FastAPI:
    engine = None
    if session_factory is None:
        engine, session_factory = make_database(settings.database_url.get_secret_value())
    provider = market_data_provider(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title="TradePilot API",
        version="0.1.0",
        lifespan=lifespan,
        description="모의투자 서버. 증권사 API 및 AI 모델은 미연결입니다.",
    )
    app.state.sessions = session_factory
    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )
    bearer = HTTPBearer(auto_error=False)

    def get_db():
        with session_factory.begin() as db:
            yield db

    # Commit must succeed before an accepted-order response leaves the server.
    Db = Annotated[Session, Depends(get_db, scope="function")]

    def session_hash(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if credentials is None or len(credentials.credentials) > 512:
            raise HTTPException(401, "로그인이 필요합니다.")
        return security.digest(credentials.credentials)

    TokenHash = Annotated[str, Depends(session_hash)]

    def current_user(db: Db, token: TokenHash) -> str:
        return security.authenticate(db, token)

    UserId = Annotated[str, Depends(current_user, scope="function")]

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready(db: Db):
        # This also verifies that migrations have been applied.
        db.execute(select(User.id).limit(1))
        db.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.post("/v1/auth/login", response_model=schemas.SessionResponse, tags=["auth"])
    def login(body: schemas.Login, db: Db):
        return security.login(db, body.email, body.password, settings.session_ttl_seconds)

    @app.post("/v1/auth/logout", tags=["auth"])
    def logout(db: Db, user_id: UserId, token: TokenHash):
        db.execute(delete(WsTicket).where(WsTicket.session_hash == token))
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token))
        return {"status": "logged_out"}

    @app.get("/v1/watchlist", response_model=schemas.WatchlistResponse, tags=["market"])
    def watchlist(db: Db, user_id: UserId):
        return {
            "items": market.snapshot(db, user_id, provider),
            "market_data_mode": settings.market_data_mode,
        }

    @app.get("/v1/predictions/{symbol}", tags=["predictions"])
    def prediction(symbol: schemas.SymbolCode, user_id: UserId):
        return predictions.get_prediction(symbol)

    @app.get("/v1/market/{symbol}/candles", tags=["integration-points"])
    def candles(
        symbol: schemas.SymbolCode,
        user_id: UserId,
        interval: Annotated[str, Query(pattern="^(1m|5m|15m|1h|1d)$")] = "5m",
    ):
        # TODO(broker-candles): wire provider.get_candles() after agreeing OHLCV schema.
        return {"status": "unavailable", "reason": "candle_provider_not_configured", "items": []}

    @app.get("/v1/integrations/broker", tags=["integration-points"])
    def broker_status(user_id: UserId):
        return {
            "configured": False,
            "market_data_mode": settings.market_data_mode,
            "execution": "disabled",
            "account": "disabled",
            "fills": "disabled",
        }

    @app.post("/v1/orders/check", response_model=schemas.CheckResponse, tags=["paper-orders"])
    def check(body: schemas.Draft, db: Db, user_id: UserId):
        return orders.preflight(db, user_id, body, settings)

    @app.post("/v1/orders", response_model=schemas.Receipt, tags=["paper-orders"])
    def submit(
        body: schemas.Submit,
        db: Db,
        user_id: UserId,
        key: Annotated[
            str,
            Header(
                alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"
            ),
        ],
    ):
        return orders.submit(db, user_id, body, key, settings)

    @app.get("/v1/orders", response_model=schemas.OrderList, tags=["paper-orders"])
    def order_list(db: Db, user_id: UserId):
        rows = db.scalars(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(200)
        ).all()
        return {"items": [orders.receipt(row) for row in rows]}

    @app.post("/v1/orders/{order_id}/cancel", response_model=schemas.Receipt, tags=["paper-orders"])
    def cancel(order_id: str, db: Db, user_id: UserId):
        return orders.cancel(db, user_id, order_id)

    @app.post("/v1/ws-ticket", response_model=schemas.TicketResponse, tags=["realtime"])
    def ws_ticket(db: Db, user_id: UserId, token: TokenHash):
        return {"ticket": security.issue_ticket(db, token, settings.ws_ticket_ttl_seconds)}

    def consume(ticket):
        with session_factory.begin() as db:
            return security.consume_ticket(db, ticket)

    def poll(user_id, token, subscribed):
        with session_factory.begin() as db:
            security.authenticate(db, token)
            quotes = market.snapshot(db, user_id, provider) if subscribed else []
            return [q.model_dump(mode="json") for q in quotes]

    @app.websocket("/v1/ws")
    async def realtime(ws: WebSocket, ticket: str = ""):
        origin = ws.headers.get("origin")
        if (origin and origin not in settings.allowed_origins) or not 1 <= len(ticket) <= 128:
            await ws.close(code=1008)
            return
        try:
            user_id, token = await run_in_threadpool(consume, ticket)
        except HTTPException:
            await ws.close(code=1008)
            return
        await ws.accept()
        subscribed = False
        next_poll = 0.0
        last_client_message = time.monotonic()
        sequences: dict[str, int] = {}
        try:
            while True:
                tick = time.monotonic()
                if tick - last_client_message > 60:
                    await ws.close(code=1001)
                    return
                if tick >= next_poll:
                    for quote in await run_in_threadpool(poll, user_id, token, subscribed):
                        if quote["sequence"] > sequences.get(quote["symbol"], 0):
                            await asyncio.wait_for(
                                ws.send_json({"type": "quote", "data": quote}), 10
                            )
                            sequences[quote["symbol"]] = quote["sequence"]
                    next_poll = time.monotonic() + 2
                try:
                    message = await asyncio.wait_for(
                        ws.receive_json(), max(0.01, next_poll - time.monotonic())
                    )
                except TimeoutError:
                    continue
                last_client_message = time.monotonic()
                if not isinstance(message, dict):
                    await ws.close(code=1008)
                    return
                if message.get("type") == "ping":
                    await asyncio.wait_for(ws.send_json({"type": "pong"}), 10)
                elif message == {"type": "subscribe", "channel": "quotes"}:
                    subscribed = True
                    next_poll = 0
                else:
                    await ws.close(code=1008)
                    return
        except HTTPException:
            await ws.close(code=1008)
        except (ValueError, TimeoutError):
            await ws.close(code=1008)
        except WebSocketDisconnect:
            pass

    return app
