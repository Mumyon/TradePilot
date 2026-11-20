import asyncio
import ipaddress
import logging
import re
import time
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime
from typing import Annotated, Literal

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
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, defer
from starlette.concurrency import run_in_threadpool

from . import replay_schemas, schemas, security
from .brokers.contracts import MarketQuote
from .brokers.factory import market_data_provider
from .brokers.stream import StreamingMarketData
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
    Quote,
    ReplayCase,
    ReplayRun,
    Strategy,
    Symbol,
    TradePlan,
    User,
    Watchlist,
    WsTicket,
    now,
)
from .services import (
    ai_review,
    automation,
    backtests,
    datasets,
    decision_ai,
    historical_data,
    market,
    market_hours,
    market_overview,
    orders,
    paper_worker,
    portfolio,
    predictions,
    pretrade_ai,
    replay,
    stock_details,
    volatility_index,
)
from .services import candles as candle_service


def create_app(settings: Settings, session_factory=None) -> FastAPI:
    engine = None
    if session_factory is None:
        engine, session_factory = make_database(settings.database_url.get_secret_value())
    provider = market_data_provider(settings)

    @asynccontextmanager
    async def lifespan(app):
        if settings.market_data_mode in ("demo", "kis", "namuh", "toss"):
            from sqlalchemy.dialects.postgresql import insert

            with session_factory.begin() as db:
                names = {"005930": "삼성전자", "000660": "SK하이닉스"}
                codes = names if settings.market_data_mode in ("demo", "toss") else provider.symbols
                for code in codes:
                    name = names.get(code, code)
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
                    await run_in_threadpool(
                        ai_review.process_next, session_factory, settings, provider
                    )
                except Exception:
                    # Provider error bodies and authentication details are not logged.
                    logging.getLogger(__name__).warning("AI review worker iteration failed")
                await asyncio.sleep(2)

        async def prediction_feed():
            while True:
                try:
                    await run_in_threadpool(
                        predictions.collect_toss_candles, session_factory, provider, settings
                    )
                except Exception:
                    logging.getLogger(__name__).exception("Prediction candle collection failed")
                await asyncio.sleep(60)

        market_task = (
            asyncio.create_task(provider.run())
            if settings.market_data_mode in ("kis", "namuh", "toss")
            else None
        )
        task = asyncio.create_task(worker()) if settings.paper_worker_enabled else None
        review_task = asyncio.create_task(review_worker()) if settings.ai_review_enabled else None
        prediction_task = (
            asyncio.create_task(prediction_feed())
            if settings.market_data_mode == "toss"
            and (settings.prediction_model_directory or settings.prediction_model_path)
            else None
        )
        try:
            yield
        finally:
            if market_task is not None:
                market_task.cancel()
                with suppress(asyncio.CancelledError):
                    await market_task
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if review_task is not None:
                review_task.cancel()
                with suppress(asyncio.CancelledError):
                    await review_task
            if prediction_task is not None:
                prediction_task.cancel()
                with suppress(asyncio.CancelledError):
                    await prediction_task
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title="TradePilot API",
        version="0.1.0",
        lifespan=lifespan,
        description="모의투자 서버. KIS·나무 PLUG·토스증권 시세 연결 지원. 실계좌·실주문 미연결.",
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
                    experiment=r.state.get("experiment", "pilot"),
                    finished=r.state["finished"],
                    pair_id=r.state["pair_id"],
                    sequence=r.state["sequence"],
                    training=r.state.get("training"),
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

    @app.put("/v1/replay/runs/{run_id}/order-display/{check_id}")
    def replay_order_display(run_id: str, check_id: str, db: Db, user_id: UserId):
        return replay.record_order_display(db, user_id, run_id, check_id)

    @app.get("/v1/replay/runs/{run_id}/export")
    def replay_export(run_id: str, db: Db, user_id: UserId):
        return replay.export(db, user_id, run_id)

    def review_accessible(request: Request) -> bool:
        if settings.ai_review_provider == "openai_api" or not settings.ai_review_local_only:
            return True
        try:
            return bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
        except ValueError:
            return False

    def require_local_review(request: Request):
        if not review_accessible(request):
            raise HTTPException(403, "ChatGPT 구독 연결은 본인 로컬 실행에서 사용할 수 있습니다.")

    @app.get("/v1/market/{symbol}/ai-analysis")
    def market_ai_status(symbol: schemas.SymbolCode, request: Request, db: Db, user_id: UserId):
        require_local_review(request)
        return decision_ai.live_market(db, user_id, symbol, settings, create=False)

    @app.get("/v1/market/{symbol}/five-minute-analysis", tags=["market"])
    def five_minute_analysis(symbol: schemas.SymbolCode, db: Db, user_id: UserId):
        if db.get(Symbol, symbol) is None:
            raise HTTPException(404, "등록되지 않은 종목입니다.")
        refresh_analysis_candles(symbol)
        summary = decision_ai.recent_market_candles(
            db, symbol, settings, datetime.now(UTC), provider
        )
        return {"status": "available" if summary else "unavailable", "summary": summary}

    def refresh_analysis_candles(symbol):
        if settings.market_data_mode == "toss":
            from .brokers.toss import TossUnavailable

            with suppress(TossUnavailable):
                provider.refresh_feedback_candles(symbol)

    @app.post("/v1/market/{symbol}/ai-analysis")
    def market_ai_request(
        symbol: schemas.SymbolCode,
        body: decision_ai.MarketAnalysisRequest,
        request: Request,
        db: Db,
        user_id: UserId,
    ):
        require_local_review(request)
        if db.get(Symbol, symbol) is not None:
            refresh_analysis_candles(symbol)
        return decision_ai.live_market(
            db, user_id, symbol, settings, create=True, provider=provider, automatic=body.automatic
        )

    @app.get("/v1/replay/runs/{run_id}/decision-ai/{stage}")
    @app.put("/v1/replay/runs/{run_id}/decision-ai/{stage}")
    def replay_decision_status(
        run_id: str,
        stage: Literal["market", "order"],
        request: Request,
        db: Db,
        user_id: UserId,
        check_id: str | None = None,
    ):
        require_local_review(request)
        return decision_ai.replay_review(
            db,
            user_id,
            run_id,
            stage,
            check_id,
            settings,
            method=request.method,
        )

    @app.post("/v1/replay/runs/{run_id}/decision-ai/{stage}")
    def replay_decision_request(
        run_id: str,
        stage: Literal["market", "order"],
        body: pretrade_ai.QuantRequest,
        request: Request,
        db: Db,
        user_id: UserId,
        check_id: str | None = None,
    ):
        require_local_review(request)
        return decision_ai.replay_review(
            db, user_id, run_id, stage, check_id, settings, method="POST"
        )

    @app.get("/v1/replay/runs/{run_id}/ai-review")
    def replay_ai_status(run_id: str, request: Request, db: Db, user_id: UserId):
        require_local_review(request)
        return ai_review.review_status(db, user_id, run_id, settings)

    @app.post("/v1/replay/runs/{run_id}/training")
    def replay_training(run_id: str, request: Request, db: Db, user_id: UserId):
        require_local_review(request)
        return ai_review.start_training(db, user_id, run_id)

    @app.post("/v1/replay/runs/{run_id}/ai-review")
    def replay_ai_request(
        run_id: str, body: ai_review.ReviewRequest, request: Request, db: Db, user_id: UserId
    ):
        require_local_review(request)
        return ai_review.request_review(db, user_id, run_id, settings)

    def prompt_option(user: User, target: schemas.PromptTarget):
        if target == "chart":
            custom = user.chart_prompt
            default = decision_ai.MARKET_PROMPT
            alternate = decision_ai.MARKET_SNAPSHOT_PROMPT
        else:
            custom = user.order_prompt
            default = decision_ai.ORDER_PROMPT
            alternate = pretrade_ai.WEB_ORDER_PROMPT
        return dict(
            text=custom if custom is not None else default,
            customized=custom is not None,
            alternate_default=alternate,
        )

    @app.get("/v1/ai/prompts/{target}")
    def get_ai_prompt(target: schemas.PromptTarget, db: Db, user_id: UserId):
        return prompt_option(db.get(User, user_id), target)

    @app.put("/v1/ai/prompts/{target}")
    def update_ai_prompt(
        target: schemas.PromptTarget, body: schemas.PromptOptionUpdate, db: Db, user_id: UserId
    ):
        user = orders.lock_user(db, user_id)
        if target == "chart":
            user.chart_prompt = body.text
        else:
            user.order_prompt = body.text
        return prompt_option(user, target)

    @app.get("/v1/ai/connection")
    def ai_connection(request: Request, user_id: UserId):
        require_local_review(request)
        from .llm import chatgpt

        if settings.ai_review_provider == "openai_api":
            available = settings.ai_review_enabled and bool(settings.openai_api_key)
            return dict(
                status="connected" if available else "not_connected",
                model=settings.openai_model if available else None,
                enabled=settings.ai_review_enabled,
                command=None,
                message="시연 서버의 AI 분석을 사용합니다."
                if available
                else "시연 서버의 AI 설정을 확인해 주세요.",
            )

        result = dict(
            status="not_connected",
            model=None,
            enabled=settings.ai_review_enabled,
            command="./tool/connect_chatgpt.sh",
            message="연결 도구 실행 후 ChatGPT 로그인과 구독 사용 권한 동의를 완료하세요.",
        )
        try:
            connection = chatgpt.connection(settings.chatgpt_credentials_dir, user_id)
            result.update(
                status="connected",
                model=connection["model"],
                message="로그인 정보가 저장돼 있습니다. 실제 사용은 복기 응답 완료 시 확인됩니다.",
            )
        except chatgpt.ReviewError as exc:
            result.update(
                status=exc.code, message=ai_review.MESSAGES.get(exc.code, result["message"])
            )
        return result

    @app.get("/v1/orders/check/{check_id}/ai-feedback")
    def pretrade_status(check_id: str, request: Request, db: Db, user_id: UserId):
        require_local_review(request)
        return pretrade_ai.review_status(db, user_id, check_id, settings)

    @app.post("/v1/orders/check/{check_id}/ai-feedback")
    def pretrade_request(
        check_id: str, body: pretrade_ai.QuantRequest, request: Request, db: Db, user_id: UserId
    ):
        require_local_review(request)
        return pretrade_ai.request_review(db, user_id, check_id, settings)

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
    def system_status(user_id: UserId, db: Db):
        return {
            "mode": "paper",
            "test_mode_available": market_hours.test_mode_available(db, settings),
            "market_data_mode": settings.market_data_mode,
            "orders_halted": settings.orders_halted,
            "worker_enabled": settings.paper_worker_enabled,
            "model_configured": bool(
                settings.prediction_model_path
                or (
                    settings.prediction_model_directory
                    and any(settings.prediction_model_directory.glob("*.json"))
                )
            ),
            "real_broker_configured": False,
            "market_feed": provider.status()
            if settings.market_data_mode in ("kis", "namuh", "toss")
            else None,
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
            "instruments": dict(
                db.execute(
                    select(Symbol.symbol, Symbol.name)
                    .join(Watchlist, Watchlist.symbol == Symbol.symbol)
                    .where(Watchlist.user_id == user_id)
                    .order_by(Symbol.symbol)
                ).all()
            ),
            "market_data_mode": settings.market_data_mode,
        }

    @app.get("/v1/account", tags=["account"])
    def account(db: Db, user_id: UserId):
        return portfolio.account(
            db, user_id, settings, provider if isinstance(provider, StreamingMarketData) else None
        )

    @app.get("/v1/account/trade-profit", tags=["account"])
    def trade_profit(
        db: Db,
        user_id: UserId,
        group_by: Literal["date", "symbol"] = "date",
        start_date: date | None = None,
        end_date: date | None = None,
        symbol: Annotated[str | None, Query(pattern=r"^[A-Z0-9.]{1,16}$")] = None,
    ):
        if start_date is not None and end_date is not None and start_date > end_date:
            raise HTTPException(422, "시작일은 종료일 이전이어야 합니다.")
        return portfolio.trade_profit(db, user_id, group_by, start_date, end_date, symbol)

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

    @app.get("/v1/market/discover", tags=["market"])
    def discover_market(db: Db, user_id: UserId):
        if settings.market_data_mode not in ("namuh", "toss"):
            raise HTTPException(409, "발견 화면에서 사용할 실제 시세 제공자가 연결되지 않았습니다.")
        try:
            result = provider.discovery_snapshot()
        except Exception as exc:
            from .brokers.namuh import NamuhUnavailable
            from .brokers.toss import TossUnavailable

            if isinstance(exc, (NamuhUnavailable, TossUnavailable)):
                raise HTTPException(503, str(exc)) from None
            raise
        if settings.market_data_mode == "toss":
            from sqlalchemy.dialects.postgresql import insert

            for item in result["items"]:
                db.execute(
                    insert(Symbol)
                    .values(symbol=item["symbol"], name=item["name"])
                    .on_conflict_do_update(
                        index_elements=[Symbol.symbol], set_={"name": item["name"]}
                    )
                )
        status = provider.status()
        return {
            **result,
            "feed_state": status["state"],
            "feed_message": status["message"],
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

    @app.get("/v1/market/{symbol}/quote", tags=["market"])
    def selected_quote(symbol: schemas.SymbolCode, db: Db, user_id: UserId):
        instrument = db.get(Symbol, symbol)
        if instrument is None:
            raise HTTPException(404, "등록되지 않은 종목입니다.")
        try:
            tick = provider.get_quote(symbol)
        except Exception:
            tick = None
        if tick is not None:
            market.publish_quote(db, tick)
            db.flush()
        quote = db.get(Quote, symbol)
        expected_source = getattr(provider, "source", None)
        if quote is not None and (
            (expected_source and quote.source != expected_source)
            or (quote.source == "demo" and settings.market_data_mode != "demo")
        ):
            quote = None
        display_quote = (
            None
            if quote is None
            else schemas.QuoteResponse(
                symbol=symbol,
                name=instrument.name,
                price_won=str(quote.price_won),
                as_of=quote.as_of,
                sequence=quote.sequence,
                source=quote.source,
            )
        )
        if tick is not None and (display_quote is None or tick.as_of > display_quote.as_of):
            display_quote = schemas.QuoteResponse(
                symbol=symbol,
                name=instrument.name,
                price_won=str(tick.price_won),
                as_of=tick.as_of,
                sequence=quote.sequence if quote else 0,
                source=tick.source,
            )
        previous_close = None
        execution_quote = None
        if settings.market_data_mode == "toss":
            from .brokers.toss import TossUnavailable

            execution = provider.get_execution_quote(symbol)
            if execution:
                execution_quote = schemas.QuoteResponse(
                    symbol=symbol,
                    name=instrument.name,
                    price_won=str(execution.price_won),
                    as_of=execution.as_of,
                    sequence=0,
                    source=execution.source,
                )
            with suppress(TossUnavailable):
                previous_close = provider.get_previous_close(symbol)
        return {
            "symbol": symbol,
            "name": instrument.name,
            "previous_close_won": previous_close,
            "quote": display_quote,
            "execution_quote": execution_quote,
        }

    @app.get("/v1/liquidity/quotes", tags=["market"])
    def liquidity_quotes(
        user_id: UserId,
        symbols: Annotated[str, Query(pattern=r"^[A-Z0-9.-]{1,12}(,[A-Z0-9.-]{1,12}){0,7}$")],
    ):
        from .brokers.toss import TossMarketData, TossUnavailable

        if not isinstance(provider, TossMarketData):
            raise HTTPException(503, "토스 시세 연결이 필요합니다.")
        try:
            return {"items": provider.lab_quotes(list(dict.fromkeys(symbols.split(","))))}
        except TossUnavailable as exc:
            raise HTTPException(503, str(exc)) from None

    @app.get("/v1/liquidity/{symbol}", tags=["market"])
    def liquidity_market(
        user_id: UserId,
        symbol: str,
        view: Literal["book", "trades", "context"] = "book",
        market_code: Literal["KR", "US"] = "KR",
    ):
        from .brokers.toss import TossMarketData, TossUnavailable

        pattern = r"[A-Z0-9]{6}" if market_code == "KR" else r"[A-Z][A-Z0-9.-]{0,11}"
        if not re.fullmatch(pattern, symbol):
            raise HTTPException(422, "시장에 맞는 종목 코드를 입력하세요.")
        if not isinstance(provider, TossMarketData):
            raise HTTPException(503, "토스 시세 연결이 필요합니다.")
        try:
            if view == "context":
                return provider.lab_market_context(symbol, market_code)
            data = provider.chart_details(symbol, "orderbook" if view == "book" else "trades")
            if view == "book" and data.get("currency") != ("KRW" if market_code == "KR" else "USD"):
                raise HTTPException(503, "시세 통화와 선택 시장이 일치하지 않습니다.")
            return {**data, "source": "toss_kr" if market_code == "KR" else "toss_us"}
        except TossUnavailable as exc:
            raise HTTPException(503, str(exc)) from None

    @app.get("/v1/market/{symbol}/details/{section}", tags=["market"])
    def chart_details(
        symbol: schemas.SymbolCode,
        section: Literal["orderbook", "trades", "news", "company", "financials"],
        db: Db,
        user_id: UserId,
    ):
        instrument = db.get(Symbol, symbol)
        if instrument is None:
            raise HTTPException(404, "등록되지 않은 종목입니다.")
        if section == "news":
            try:
                return stock_details.news(settings, instrument.name)
            except (OSError, ValueError, KeyError):
                raise HTTPException(503, "뉴스 데이터를 불러오지 못했습니다.") from None
        if section == "financials":
            try:
                return stock_details.financials(settings, symbol)
            except (OSError, ValueError, KeyError, SyntaxError):
                raise HTTPException(503, "재무제표를 불러오지 못했습니다.") from None
        from .brokers.toss import TossMarketData, TossUnavailable

        if not isinstance(provider, TossMarketData):
            return {"status": "unsupported"}
        try:
            return provider.chart_details(symbol, section)
        except TossUnavailable as exc:
            raise HTTPException(503, str(exc)) from None

    @app.get("/v1/market/volatility-index", tags=["market"])
    def vix(user_id: UserId):
        return volatility_index.latest()

    @app.get("/v1/market/overview", tags=["market"])
    def overview(user_id: UserId):
        return market_overview.latest()

    @app.get("/v1/market/{symbol}/candles", tags=["integration-points"])
    def candles(
        symbol: schemas.SymbolCode,
        user_id: UserId,
        db: Db,
        interval: Annotated[str, Query(pattern="^(1m|3m|5m|10m|15m|30m|1h|1d|1w|1mo|1y)$")] = "5m",
    ):
        if db.get(Symbol, symbol) is None:
            raise HTTPException(404, "등록되지 않은 종목입니다.")
        if settings.market_data_mode == "toss":
            from .brokers.toss import TossUnavailable

            try:
                rows = provider.get_chart_candles(symbol, interval)
            except TossUnavailable as exc:
                raise HTTPException(503, str(exc)) from None
            now = datetime.now(UTC)
            latest = rows[-1] if rows else None
            return {
                "status": "available" if rows else "unavailable",
                "interval": interval,
                "source": "toss_kr" if rows else None,
                "stale": latest is None
                or now - latest["closed_at"] > candle_service.chart_staleness(interval),
                "as_of": latest["closed_at"] if latest else None,
                "items": [
                    {
                        **row,
                        "opened_at": row["opened_at"],
                        "open_won": str(row["open_won"]),
                        "high_won": str(row["high_won"]),
                        "low_won": str(row["low_won"]),
                        "close_won": str(row["close_won"]),
                    }
                    for row in rows
                ],
            }
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

    def test_order_quote(db, body):
        if not body.test_mode or not market_hours.test_mode_available(db, settings):
            return None
        return MarketQuote(
            body.symbol, int(body.limit_price_won), now(), "test_mode", executable=False
        )

    @app.post("/v1/orders/check", response_model=schemas.CheckResponse, tags=["paper-orders"])
    def check(body: schemas.Draft, db: Db, user_id: UserId):
        return orders.preflight(db, user_id, body, settings, test_quote=test_order_quote(db, body))

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
        return orders.submit(
            db, user_id, body, key, settings, test_quote=test_order_quote(db, body)
        )

    @app.get("/v1/orders", response_model=schemas.OrderList, tags=["paper-orders"])
    def order_list(db: Db, user_id: UserId):
        rows = db.scalars(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(200)
        ).all()
        return {"items": [orders.receipt(row) for row in rows]}

    @app.get("/v1/journal/{target}/{target_id}/ai-review", tags=["journal"])
    def journal_ai_status(
        target: Literal["orders", "deferred", "samples"],
        target_id: str,
        request: Request,
        db: Db,
        user_id: UserId,
    ):
        from .services.journal_ai import review

        require_local_review(request)
        return review(db, user_id, target, target_id, settings, create=False)

    @app.post("/v1/journal/{target}/{target_id}/ai-review", tags=["journal"])
    def journal_ai_request(
        target: Literal["orders", "deferred", "samples"],
        target_id: str,
        body: ai_review.ReviewRequest,
        request: Request,
        db: Db,
        user_id: UserId,
    ):
        from .services.journal_ai import review

        require_local_review(request)
        return review(db, user_id, target, target_id, settings, create=True)

    @app.get("/v1/journal", tags=["journal"])
    def journal_report(
        request: Request,
        db: Db,
        user_id: UserId,
        days: int = Query(default=30, ge=1, le=365),
        offset: int = Query(default=0, ge=0),
        include_pretrade: bool = False,
    ):
        from .services.journal import report

        predictions.resolve_outcomes(db)
        return report(
            db,
            user_id,
            days,
            offset,
            include_pretrade=include_pretrade,
            include_ai=include_pretrade and review_accessible(request),
        )

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

    def chart_symbol_name(user_id, token, symbol):
        with session_factory.begin() as db:
            if security.authenticate(db, token) != user_id:
                return None
            return db.scalar(select(Symbol.name).where(Symbol.symbol == symbol))

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
        chart_quotes = asyncio.Queue(maxsize=1)

        async def send_chart_quotes():
            while True:
                quote, name = await chart_quotes.get()
                event = schemas.QuoteResponse(
                    symbol=quote.symbol,
                    name=name,
                    price_won=str(quote.price_won),
                    as_of=quote.as_of,
                    sequence=0,
                    source=quote.source,
                )
                await asyncio.wait_for(
                    ws.send_json({"type": "chart_quote", "data": event.model_dump(mode="json")}), 10
                )

        chart_task = (
            asyncio.create_task(send_chart_quotes())
            if settings.market_data_mode == "toss"
            else None
        )
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
                elif message.get("type") == "chart_symbol" and "symbol" in message:
                    symbol = message["symbol"]
                    if symbol is not None and (
                        not isinstance(symbol, str) or not re.fullmatch(r"[0-9A-Z.]{1,16}", symbol)
                    ):
                        await ws.close(code=1008)
                        return
                    if chart_task is not None:
                        provider.set_chart_subscription(chart_quotes)
                        if symbol is not None and re.fullmatch(r"[0-9]{6}", symbol):
                            name = await run_in_threadpool(
                                chart_symbol_name, user_id, token, symbol
                            )
                            if name:
                                provider.set_chart_subscription(chart_quotes, symbol, name)
                else:
                    await ws.close(code=1008)
                    return
        except HTTPException:
            await ws.close(code=1008)
        except (ValueError, TimeoutError):
            await ws.close(code=1008)
        except WebSocketDisconnect:
            pass
        finally:
            if chart_task is not None:
                provider.set_chart_subscription(chart_quotes)
                chart_task.cancel()
                with suppress(
                    asyncio.CancelledError, WebSocketDisconnect, TimeoutError, RuntimeError
                ):
                    await chart_task

    if settings.web_build_dir is not None:
        app.mount("/", StaticFiles(directory=settings.web_build_dir, html=True), name="web-demo")

    return app
