import logging

from sqlalchemy import select

from ..brokers.contracts import BrokerNotConfigured
from ..models import Automation, Order, Symbol
from . import automation
from .market import publish_quote
from .portfolio import settle
from .predictions import resolve_outcomes

logger = logging.getLogger(__name__)


def tick(sessions, provider, settings):
    # Market updates commit before taking account locks. Requests never depend on
    # an open app/watchlist, and multiple workers serialize on each user row.
    with sessions.begin() as db:
        for symbol in db.scalars(select(Symbol.symbol).order_by(Symbol.symbol)).all():
            try:
                quote = provider.get_quote(symbol)
            except BrokerNotConfigured:
                continue
            if quote is not None:
                publish_quote(db, quote)
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
