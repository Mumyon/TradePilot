from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("cash_won >= 0 AND reserved_won >= 0 AND reserved_won <= cash_won"),
        CheckConstraint("order_limit_won > 0 AND daily_loss_limit_won > 0"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    cash_won: Mapped[int] = mapped_column(BigInteger, default=10_000_000)
    reserved_won: Mapped[int] = mapped_column(BigInteger, default=0)
    order_limit_won: Mapped[int] = mapped_column(BigInteger, default=1_000_000)
    cooldown_seconds: Mapped[int] = mapped_column(BigInteger, default=300)
    trading_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    trading_rules: Mapped[str] = mapped_column(String(2000), default="")
    daily_loss_limit_won: Mapped[int] = mapped_column(BigInteger, default=1_000_000)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class WsTicket(Base):
    __tablename__ = "ws_tickets"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_hash: Mapped[str] = mapped_column(ForeignKey("auth_sessions.token_hash"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Symbol(Base):
    __tablename__ = "symbols"
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class Watchlist(Base):
    __tablename__ = "watchlists"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("symbols.symbol"), primary_key=True)


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (CheckConstraint("price_won > 0 AND sequence > 0"),)
    symbol: Mapped[str] = mapped_column(ForeignKey("symbols.symbol"), primary_key=True)
    price_won: Mapped[int] = mapped_column(BigInteger)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sequence: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32))


class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (CheckConstraint("quantity >= 0 AND reserved >= 0 AND reserved <= quantity"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("symbols.symbol"), primary_key=True)
    quantity: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_won: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class OrderCheck(Base):
    __tablename__ = "order_checks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    decision: Mapped[str] = mapped_column(String(16), default="pending")
    decision_reason: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    origin: Mapped[str] = mapped_column(String(16), default="manual")
    presented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_order_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    draft: Mapped[dict] = mapped_column(JSON)
    allowed: Mapped[bool] = mapped_column(Boolean)
    messages: Mapped[list] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_order_user_key"),
        CheckConstraint("quantity > 0 AND limit_price_won > 0"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_body: Mapped[dict] = mapped_column(JSON)
    symbol: Mapped[str] = mapped_column(ForeignKey("symbols.symbol"))
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[int] = mapped_column(BigInteger)
    limit_price_won: Mapped[int] = mapped_column(BigInteger)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("trade_plans.id"), nullable=True)
    review_note: Mapped[str] = mapped_column(String(2000), default="")
    review_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    plan_group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reserved_cash_won: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class TradePlan(Base):
    __tablename__ = "trade_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("symbols.symbol"))
    side: Mapped[str] = mapped_column(String(4))
    entry_min_won: Mapped[int | None] = mapped_column(BigInteger)
    entry_max_won: Mapped[int | None] = mapped_column(BigInteger)
    entry_condition: Mapped[str] = mapped_column(String(1000))
    stop_loss_won: Mapped[int | None] = mapped_column(BigInteger)
    max_amount_won: Mapped[int] = mapped_column(BigInteger)
    split_order: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Candle(Base):
    __tablename__ = "candles"
    symbol: Mapped[str] = mapped_column(ForeignKey("symbols.symbol"), primary_key=True)
    interval: Mapped[str] = mapped_column(String(4), primary_key=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    open_won: Mapped[int] = mapped_column(BigInteger)
    high_won: Mapped[int] = mapped_column(BigInteger)
    low_won: Mapped[int] = mapped_column(BigInteger)
    close_won: Mapped[int] = mapped_column(BigInteger)
    volume: Mapped[int] = mapped_column(BigInteger)
    complete: Mapped[bool] = mapped_column(Boolean)


class Fill(Base):
    __tablename__ = "fills"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("symbols.symbol"))
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[int] = mapped_column(BigInteger)
    price_won: Mapped[int] = mapped_column(BigInteger)
    fee_won: Mapped[int] = mapped_column(BigInteger)
    realized_pnl_won: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32))
    quote_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class QuoteSample(Base):
    __tablename__ = "quote_samples"
    symbol: Mapped[str] = mapped_column(ForeignKey("symbols.symbol"), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, index=True)
    price_won: Mapped[int] = mapped_column(BigInteger)


class PredictionRecord(Base):
    __tablename__ = "prediction_records"
    __table_args__ = (
        UniqueConstraint("symbol", "as_of", "model_version", name="uq_prediction_bar_model"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    symbol: Mapped[str] = mapped_column(ForeignKey("symbols.symbol"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    target_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    model_version: Mapped[str] = mapped_column(String(64))
    base_price_won: Mapped[int] = mapped_column(BigInteger)
    data: Mapped[dict] = mapped_column(JSON)
    outcome: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)


class Strategy(Base):
    __tablename__ = "strategies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    config: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Backtest(Base):
    __tablename__ = "backtests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Automation(Base):
    __tablename__ = "automations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    strategy_id: Mapped[str] = mapped_column(ForeignKey("strategies.id"), unique=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("symbols.symbol"))
    snapshot: Mapped[dict] = mapped_column(JSON)
    budget_won: Mapped[int] = mapped_column(BigInteger)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_bar: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str] = mapped_column(String(1000), default="시작 대기")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AutomationEvent(Base):
    __tablename__ = "automation_events"
    __table_args__ = (UniqueConstraint("automation_id", "bar_at", name="uq_automation_bar"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    automation_id: Mapped[str] = mapped_column(ForeignKey("automations.id"), index=True)
    bar_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    signal: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(String(1000))
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    symbol: Mapped[str] = mapped_column(ForeignKey("symbols.symbol"))
    provider: Mapped[str] = mapped_column(String(100))
    data_kind: Mapped[str] = mapped_column(String(16))
    rows: Mapped[list] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReplayCase(Base):
    __tablename__ = "replay_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    config: Mapped[dict] = mapped_column(JSON)
    rows: Mapped[list] = mapped_column(JSON)
    artifact: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReplayRun(Base):
    __tablename__ = "replay_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("replay_cases.id"), index=True)
    state: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AIReview(Base):
    __tablename__ = "ai_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("replay_runs.id"), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(BigInteger, default=1)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
