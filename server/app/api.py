import asyncio
import ipaddress
import logging
import time
from contextlib import asynccontextmanager, suppress
from datetime import UTC
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, defer
from starlette.concurrency import run_in_threadpool

from . import replay_schemas, schemas, security
from .brokers.factory import market_data_provider
from .config import Settings
from .db import make_database
from .models import (
    AIReview,
    AuthSession,
    Automation,
    AutomationEvent,
    Backtest,
    Dataset,
    Fill,
    Order,
    ReplayCase,
    ReplayRun,
    Strategy,
    Symbol,
    TradePlan,
    User,
    Watchlist,
    WsTicket,
)
from .services import (
    ai_review,
    automation,
    backtests,
    datasets,
    historical_data,
    market,
    orders,
    paper_worker,
    portfolio,
    predictions,
    replay,
)
from .services import candles as candle_service


def create_app(settings: Settings, session_factory=None) -> FastAPI:
    engine = None
    if session_factory is None:
        engine, session_factory = make_database(settings.database_url.get_secret_value())
    provider = market_data_provider(settings)

    @asynccontextmanager
    async def lifespan(app):
        if settings.market_data_mode == "demo":
            from sqlalchemy.dialects.postgresql import insert

            with session_factory.begin() as db:
                for code, name in [("005930", "삼성전자"), ("000660", "SK하이닉스")]:
                    db.execute(
                        insert(Symbol).values(symbol=code, name=name).on_conflict_do_nothing()
                    )

        async def worker():
            while True:
                try:
                    await run_in_threadpool(paper_worker.tick, session_factory, provider, settings)
                except Exception:
                    logging.getLogger(__name__).exception("Paper worker iteration failed")
                await asyncio.sleep(2)

        async def review_worker():
            while True:
                try:
                    await run_in_threadpool(ai_review.process_next, session_factory, settings)
                except Exception:
                    # Provider error bodies and authentication details are not logged.
                    logging.getLogger(__name__).warning("AI review worker iteration failed")
                await asyncio.sleep(2)

        task = asyncio.create_task(worker()) if settings.paper_worker_enabled else None
        review_task = asyncio.create_task(review_worker()) if settings.ai_review_enabled else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if review_task is not None:
                review_task.cancel()
                with suppress(asyncio.CancelledError):
                    await review_task
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title="TradePilot API",
        version="0.1.0",
        lifespan=lifespan,
        description="모의투자 서버. 로컬 AI 학습·과거 사례 재생 지원. 증권사 API 미연결.",
    )
    app.state.sessions = session_factory
    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
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

    @app.get("/v1/replay")
    def replay_hub(db: Db, user_id: UserId):
        cases = db.scalars(
            select(ReplayCase)
            .where(ReplayCase.user_id == user_id)
            .order_by(ReplayCase.created_at.desc())
        ).all()
        runs = db.scalars(
            select(ReplayRun)
            .where(ReplayRun.user_id == user_id)
            .order_by(ReplayRun.created_at.desc())
        ).all()
        by_id = {c.id: c for c in cases}
        return dict(
            events=replay.EVENTS,
            cases=[
                replay.case_view(c)
                for c in sorted(cases, key=lambda c: c.config["data_kind"] != "historical")
            ],
            runs=[
                dict(
                    id=r.id,
                    case_id=r.case_id,
                    name=by_id[r.case_id].config["name"],
                    pilot_enabled=r.state["pilot_enabled"],
                    finished=r.state["finished"],
                    pair_id=r.state["pair_id"],
                    sequence=r.state["sequence"],
                    allocation_method=r.state.get("allocation_method", "user_selected"),
                    condition_order=r.state.get("condition_order"),
                    comparison_key=r.state["comparison_key"],
                    summary=replay.summary(by_id[r.case_id], r.state)
                    if r.state["finished"]
                    else None,
                )
                for r in runs
            ],
        )

    @app.post("/v1/replay/historical")
    def replay_historical(db: Db, user_id: UserId):
        return historical_data.install(db, user_id)

    @app.post("/v1/replay/practice")
    def replay_practice(db: Db, user_id: UserId):
        return replay.practice(db, user_id)

    @app.post("/v1/replay/cases")
    def replay_case(body: replay_schemas.CaseCreate, db: Db, user_id: UserId):
        return replay.create_case(db, user_id, body)

    @app.post("/v1/replay/cases/{case_id}/train")
    def replay_train(case_id: str, db: Db, user_id: UserId):
        return replay.train_case(db, user_id, case_id)

    @app.post("/v1/replay/cases/{case_id}/runs")
    def replay_start(case_id: str, body: replay_schemas.Start, db: Db, user_id: UserId):
        return replay.start(db, user_id, case_id, body)

    @app.get("/v1/replay/runs/{run_id}")
    def replay_read(run_id: str, db: Db, user_id: UserId):
        r = replay.run_owned(db, user_id, run_id)
        return replay.view(replay.case_owned(db, user_id, r.case_id), r)

    @app.post("/v1/replay/runs/{run_id}/actions")
    def replay_action(run_id: str, body: replay_schemas.Action, db: Db, user_id: UserId):
        return replay.apply(db, user_id, run_id, body)

    @app.get("/v1/replay/runs/{run_id}/export")
    def replay_export(run_id: str, db: Db, user_id: UserId):
        return replay.export(db, user_id, run_id)

    def require_local_review(request: Request):
        if settings.ai_review_local_only:
            try:
                local = request.client and ipaddress.ip_address(request.client.host).is_loopback
            except ValueError:
                local = False
            if not local:
                raise HTTPException(
                    403, "ChatGPT 구독 연결은 본인 로컬 실행에서 사용할 수 있습니다."
                )

    @app.get("/v1/replay/runs/{run_id}/ai-review")
    def replay_ai_status(run_id: str, request: Request, db: Db, user_id: UserId):
        require_local_review(request)
        return ai_review.review_status(db, user_id, run_id, settings)

    @app.post("/v1/replay/runs/{run_id}/ai-review")
    def replay_ai_request(
        run_id: str, body: ai_review.ReviewRequest, request: Request, db: Db, user_id: UserId
    ):
        require_local_review(request)
        return ai_review.request_review(db, user_id, run_id, settings)

    @app.post("/v1/datasets/validate")
    def dataset_validate(body: schemas.DatasetUpload, user_id: UserId):
        _, summary = datasets.parse(body)
        return summary

    @app.post("/v1/datasets", status_code=201)
    def dataset_save(body: schemas.DatasetUpload, db: Db, user_id: UserId):
        return datasets.save(db, user_id, body)

    @app.get("/v1/datasets")
    def dataset_list(db: Db, user_id: UserId):
        rows = db.scalars(
            select(Dataset)
            .options(defer(Dataset.rows))
            .where(Dataset.user_id == user_id)
            .order_by(Dataset.created_at.desc())
        ).all()
        return {"items": [datasets.serialize(item) for item in rows]}

    @app.delete("/v1/datasets/{dataset_id}")
    def dataset_delete(dataset_id: str, db: Db, user_id: UserId):
        orders.lock_user(db, user_id)
        db.delete(datasets.owned(db, user_id, dataset_id))
        return {"deleted": True}

    @app.get("/v1/automations")
    def automation_list(db: Db, user_id: UserId):
        rows = db.scalars(
            select(Automation)
            .where(Automation.user_id == user_id)
            .order_by(Automation.created_at.desc())
        ).all()
        return {"items": [automation.serialize(row) for row in rows]}

    @app.put("/v1/strategies/{strategy_id}/automation")
    def automation_configure(
        strategy_id: str, body: schemas.AutomationRequest, db: Db, user_id: UserId
    ):
        return automation.configure(db, user_id, strategy_id, body, settings)

    @app.get("/v1/automations/{automation_id}/events")
    def automation_events(
        automation_id: str, db: Db, user_id: UserId, offset: int = Query(default=0, ge=0)
    ):
        item = db.get(Automation, automation_id)
        if item is None or item.user_id != user_id:
            raise HTTPException(404, "자동매매 실행을 찾을 수 없습니다.")
        rows = db.execute(
            select(AutomationEvent, Order.status)
            .outerjoin(Order, Order.id == AutomationEvent.order_id)
            .where(AutomationEvent.automation_id == item.id)
            .order_by(AutomationEvent.bar_at.desc())
            .offset(offset)
            .limit(50)
        ).all()
        return {
            "items": [
                dict(
                    id=e.id,
                    bar_at=e.bar_at,
                    signal=e.signal,
                    message=e.message,
                    order_id=e.order_id,
                    order_status=status,
                )
                for e, status in rows
            ],
            "next_offset": offset + len(rows) if len(rows) == 50 else None,
        }

    @app.get("/v1/strategies")
    def strategies_list(db: Db, user_id: UserId):
        rows = db.scalars(
            select(Strategy).where(Strategy.user_id == user_id).order_by(Strategy.created_at.desc())
        ).all()
        return {"items": [dict(id=r.id, **r.config) for r in rows]}

    @app.post("/v1/strategies", status_code=201)
    def strategy_create(body: schemas.StrategyConfig, db: Db, user_id: UserId):
        if db.get(Symbol, body.symbol) is None:
            raise HTTPException(422, "등록되지 않은 종목입니다.")
        item = Strategy(user_id=user_id, config=body.model_dump())
        db.add(item)
        db.flush()
        return dict(id=item.id, **item.config)

    @app.put("/v1/strategies/{strategy_id}")
    def strategy_update(strategy_id: str, body: schemas.StrategyConfig, db: Db, user_id: UserId):
        orders.lock_user(db, user_id)
        item = backtests.owned(db, user_id, strategy_id)
        if db.get(Symbol, body.symbol) is None:
            raise HTTPException(422, "등록되지 않은 종목입니다.")
        item.config = body.model_dump()
        if not body.enabled:
            run = db.scalar(select(Automation).where(Automation.strategy_id == strategy_id))
            if run is not None:
                automation.stop(db, run, "전략 비활성화로 자동 중지 · 미체결 취소")
        return dict(id=item.id, **item.config)

    @app.post("/v1/strategies/{strategy_id}/backtests", status_code=201)
    def backtest_run(strategy_id: str, body: schemas.BacktestRequest, db: Db, user_id: UserId):
        item = backtests.owned(db, user_id, strategy_id)
        if body.source == "demo" and body.dataset_id is None:
            if settings.market_data_mode != "demo":
                raise HTTPException(422, "합성 데이터는 시연 서버에서만 생성할 수 있습니다.")
            candle_service.ingest(
                db, item.config["symbol"], "5m", provider.get_candles(item.config["symbol"], "5m")
            )
        return backtests.run(db, user_id, strategy_id, body)

    @app.get("/v1/backtests")
    def backtests_list(db: Db, user_id: UserId, offset: int = Query(default=0, ge=0)):
        rows = db.scalars(
            select(Backtest)
            .where(Backtest.user_id == user_id)
            .order_by(Backtest.created_at.desc(), Backtest.id)
            .offset(offset)
            .limit(20)
        ).all()
        return {
            "items": [
                dict(
                    id=r.id,
                    created_at=r.created_at,
                    **{k: v for k, v in r.result.items() if k not in ("trades", "equity_curve")},
                )
                for r in rows
            ],
            "next_offset": offset + len(rows) if len(rows) == 20 else None,
        }

    @app.get("/v1/backtests/{result_id}")
    def backtest_detail(result_id: str, db: Db, user_id: UserId):
        item = db.get(Backtest, result_id)
        if item is None or item.user_id != user_id:
            raise HTTPException(404, "결과를 찾을 수 없습니다.")
        return dict(id=item.id, created_at=item.created_at, **item.result)

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready(db: Db):
        # This also verifies that migrations have been applied.
        db.execute(select(User.id).limit(1))
        db.execute(select(Order.review_note).limit(1))
        db.execute(select(Strategy.id).limit(1))
        db.execute(select(Backtest.id).limit(1))
        db.execute(select(AutomationEvent.id).limit(1))
        db.execute(select(Dataset.id).limit(1))
        db.execute(select(AIReview.id).limit(1))
        db.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.post("/v1/auth/signup", status_code=201, tags=["auth"])
    def signup(body: schemas.Signup, db: Db):
        return security.signup(db, body)

    @app.get("/v1/system/status", tags=["health"])
    def system_status(user_id: UserId):
        return {
            "mode": "paper",
            "market_data_mode": settings.market_data_mode,
            "orders_halted": settings.orders_halted,
            "worker_enabled": settings.paper_worker_enabled,
            "model_configured": bool(settings.prediction_model_path),
            "real_broker_configured": False,
            "schema_version": "20261023_replay",
        }

    @app.put("/v1/orders/{order_id}/note", tags=["journal"])
    def review_note(order_id: str, body: schemas.JournalNote, db: Db, user_id: UserId):
        from .models import now

        orders.lock_user(db, user_id)
        order = db.scalar(select(Order).where(Order.id == order_id, Order.user_id == user_id))
        if order is None:
            raise HTTPException(404, "주문을 찾을 수 없습니다.")
        order.review_note = body.text.strip()
        order.review_updated_at = now()
        return {"text": order.review_note, "updated_at": order.review_updated_at}

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

    @app.get("/v1/account", tags=["account"])
    def account(db: Db, user_id: UserId):
        return portfolio.account(db, user_id, settings)

    @app.get("/v1/settings", tags=["account"])
    def preferences(db: Db, user_id: UserId):
        user = db.get(User, user_id)
        return {field: getattr(user, field) for field in schemas.Preferences.model_fields}

    @app.put("/v1/settings", tags=["account"])
    def save_preferences(body: schemas.Preferences, db: Db, user_id: UserId):
        user = orders.lock_user(db, user_id)
        for key in body.model_fields_set:
            setattr(user, key, getattr(body, key))
        return {field: getattr(user, field) for field in schemas.Preferences.model_fields}

    @app.get("/v1/plans", tags=["account"])
    def plans(db: Db, user_id: UserId):
        rows = db.scalars(
            select(TradePlan)
            .where(TradePlan.user_id == user_id)
            .order_by(TradePlan.created_at.desc())
            .limit(200)
        ).all()
        return {
            "items": [
                dict(
                    id=p.id,
                    created_at=p.created_at,
                    **{f: getattr(p, f) for f in schemas.PlanInput.model_fields},
                )
                for p in rows
            ]
        }

    @app.post("/v1/plans", tags=["account"])
    def save_plan(body: schemas.PlanInput, db: Db, user_id: UserId):
        if db.get(Symbol, body.symbol) is None:
            raise HTTPException(404, "등록되지 않은 종목입니다.")
        plan = TradePlan(user_id=user_id, **body.model_dump())
        db.add(plan)
        db.flush()
        return {"id": plan.id, "created_at": plan.created_at, **body.model_dump()}

    @app.get("/v1/symbols", tags=["market"])
    def symbols(db: Db, user_id: UserId, q: str = Query(default="", max_length=100)):
        watched = set(db.scalars(select(Watchlist.symbol).where(Watchlist.user_id == user_id)))
        rows = db.scalars(
            select(Symbol)
            .where(
                Symbol.name.contains(q, autoescape=True)
                | Symbol.symbol.contains(q, autoescape=True)
            )
            .order_by(Symbol.symbol)
            .limit(100)
        ).all()
        return {
            "items": [dict(symbol=r.symbol, name=r.name, watched=r.symbol in watched) for r in rows]
        }

    @app.put("/v1/watchlist/{symbol}", tags=["market"])
    def add_watch(symbol: schemas.SymbolCode, db: Db, user_id: UserId):
        orders.lock_user(db, user_id)
        if db.get(Symbol, symbol) is None:
            raise HTTPException(404, "등록되지 않은 종목입니다.")
        if db.get(Watchlist, (user_id, symbol)) is None:
            db.add(Watchlist(user_id=user_id, symbol=symbol))
        return {"status": "added"}

    @app.delete("/v1/watchlist/{symbol}", tags=["market"])
    def remove_watch(symbol: schemas.SymbolCode, db: Db, user_id: UserId):
        orders.lock_user(db, user_id)
        db.execute(
            delete(Watchlist).where(Watchlist.user_id == user_id, Watchlist.symbol == symbol)
        )
        return {"status": "removed"}

    @app.get("/v1/fills", tags=["paper-orders"])
    def fills(db: Db, user_id: UserId):
        rows = db.scalars(
            select(Fill).where(Fill.user_id == user_id).order_by(Fill.created_at.desc()).limit(200)
        ).all()
        return {
            "items": [
                dict(
                    id=f.id,
                    order_id=f.order_id,
                    symbol=f.symbol,
                    side=f.side,
                    quantity=f.quantity,
                    price_won=str(f.price_won),
                    fee_won=str(f.fee_won),
                    realized_pnl_won=None
                    if f.realized_pnl_won is None
                    else str(f.realized_pnl_won),
                    source=f.source,
                    quote_as_of=f.quote_as_of,
                    created_at=f.created_at,
                )
                for f in rows
            ]
        }

    @app.get("/v1/predictions/{symbol}", tags=["predictions"])
    def prediction(symbol: schemas.SymbolCode, db: Db, user_id: UserId):
        return predictions.get_prediction(db, symbol, settings)

    @app.get("/v1/market/{symbol}/candles", tags=["integration-points"])
    def candles(
        symbol: schemas.SymbolCode,
        user_id: UserId,
        db: Db,
        interval: Annotated[str, Query(pattern="^(1m|5m|15m|1h|1d)$")] = "5m",
    ):
        if db.get(Symbol, symbol) is None:
            raise HTTPException(404, "등록되지 않은 종목입니다.")
        return candle_service.history(db, symbol, interval, provider, settings.market_data_mode)

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

    @app.get("/v1/journal", tags=["journal"])
    def journal_report(
        db: Db,
        user_id: UserId,
        days: int = Query(default=30, ge=1, le=365),
        offset: int = Query(default=0, ge=0),
    ):
        from .services.journal import report

        predictions.resolve_outcomes(db)
        return report(db, user_id, days, offset)

    @app.get("/v1/feedback", tags=["journal"])
    def feedback_report(
        db: Db,
        user_id: UserId,
        days: int = Query(default=30, ge=1, le=365),
        offset: int = Query(default=0, ge=0),
    ):
        from .services.feedback import report

        return report(db, user_id, days, offset)

    @app.get("/v1/feedback/export", tags=["journal"])
    def feedback_export(db: Db, user_id: UserId, days: int = Query(default=30, ge=1, le=365)):
        from .services.feedback import export

        return export(db, user_id, days)

    @app.post("/v1/orders/check/{check_id}/presented", tags=["paper-orders"])
    def presented_check(check_id: str, db: Db, user_id: UserId):
        from .models import OrderCheck, now

        orders.lock_user(db, user_id)
        check = db.get(OrderCheck, check_id)
        if check is None or check.user_id != user_id:
            raise HTTPException(404, "점검 기록을 찾을 수 없습니다.")
        if check.presented_at is None:
            if (
                check.origin != "manual"
                or not check.allowed
                or check.consumed
                or check.expires_at <= now()
            ):
                raise HTTPException(409, "표시 시점을 기록할 수 없는 점검입니다.")
            check.presented_at = now()
        return {"presented_at": check.presented_at.astimezone(UTC)}

    @app.post("/v1/orders/check/{check_id}/dismiss", tags=["paper-orders"])
    def dismiss_check(
        check_id: str, db: Db, user_id: UserId, body: schemas.CheckDismiss | None = None
    ):
        from .models import OrderCheck, now

        orders.lock_user(db, user_id)
        check = db.get(OrderCheck, check_id)
        if check is None or check.user_id != user_id:
            raise HTTPException(404, "점검 기록을 찾을 수 없습니다.")
        reason = body.reason.strip() if body else ""
        if check.origin != "manual":
            raise HTTPException(409, "수동 점검만 보류할 수 있습니다.")
        if check.decision == "dismissed":
            if body is not None and reason != check.decision_reason:
                raise HTTPException(409, "이미 저장한 보류 이유와 다릅니다.")
            return {"decision": check.decision, "reason": check.decision_reason}
        if check.decision != "pending" or check.consumed:
            raise HTTPException(409, "이미 처리한 점검은 보류로 변경할 수 없습니다.")
        if check.decision == "pending":
            check.decision = "dismissed"
            check.decision_reason = reason
            check.decided_at = now()
            check.consumed = True
        return {"decision": check.decision, "reason": check.decision_reason}

    @app.get("/v1/orders/{order_id}/analysis", tags=["paper-orders"])
    def order_analysis(order_id: str, db: Db, user_id: UserId):
        order = db.scalar(select(Order).where(Order.id == order_id, Order.user_id == user_id))
        if order is None:
            raise HTTPException(404, "주문을 찾을 수 없습니다.")
        return order.analysis

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
