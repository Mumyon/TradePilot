import logging

from sqlalchemy import func, select

from ..brokers.contracts import BrokerNotConfigured
from ..models import Automation, Candle, Holding, Order, Symbol, Watchlist
from . import automation, candles, market_hours
from .market import publish_quote
from .portfolio import settle
from .predictions import resolve_outcomes

logger = logging.getLogger(__name__)


def tick(sessions, provider, settings):
    # Market updates commit before taking account locks. Requests never depend on
    # an open app/watchlist, and multiple workers serialize on each user row.
    with sessions.begin() as db:
        market_hours.refresh(db, provider, settings)
        if settings.market_data_mode == "toss":
            order_symbols = list(
                db.scalars(
                    select(Order.symbol)
                    .where(Order.status == "accepted")
                    .order_by(Order.created_at)
                )
            )
            priority = list(
                db.scalars(
                    select(Holding.symbol).where(Holding.quantity > 0).order_by(Holding.symbol)
                )
            )
            priority += list(db.scalars(select(Watchlist.symbol).order_by(Watchlist.symbol)))
            provider.set_priority_symbols(priority, orders=order_symbols)
        for symbol in db.scalars(select(Symbol.symbol).order_by(Symbol.symbol)).all():
            try:
                getter = getattr(provider, "get_execution_quote", provider.get_quote)
                quote = getter(symbol)
            except (BrokerNotConfigured, RuntimeError):
                continue
            if quote is not None:
                publish_quote(db, quote)
            if settings.market_data_mode in ("kis", "namuh"):
                for interval in ("1m", "5m", "15m", "1h"):
                    latest = db.scalar(
                        select(func.max(Candle.opened_at)).where(
                            Candle.symbol == symbol,
                            Candle.interval == interval,
                            Candle.source == provider.source,
                            Candle.complete.is_(True),
                        )
                    )
                    rows = provider.get_candles(symbol, interval)
                    candles.ingest(
                        db,
                        symbol,
                        interval,
                        [row for row in rows if latest is None or row["opened_at"] > latest],
                    )
    with sessions.begin() as db:
        resolve_outcomes(db)
    with sessions() as db:
        runs = db.scalars(
            select(Automation.id)
            .where(Automation.enabled.is_(True))
            .order_by(Automation.user_id, Automation.id)
        ).all()
    for automation_id in runs:
        try:
            with sessions.begin() as db:
                automation.process(db, automation_id, provider, settings)
        except Exception:
            logger.exception("Paper automation failed; transaction rolled back")
    with sessions() as db:
        users = db.scalars(select(Order.user_id).where(Order.status == "accepted").distinct()).all()
    for user_id in sorted(users):
        try:
            with sessions.begin() as db:
                settle(db, user_id, settings)
        except Exception:
            logger.exception("Paper settlement failed; transaction rolled back")
