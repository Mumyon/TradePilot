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


class OrderCheck(Base):
    __tablename__ = "order_checks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
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
    status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
