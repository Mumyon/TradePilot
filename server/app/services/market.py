from datetime import timedelta

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..brokers.contracts import BrokerNotConfigured, MarketDataPort, MarketQuote
from ..brokers.demo import DemoMarketData
from ..brokers.stream import StreamingMarketData
from ..brokers.toss import TossMarketData
from ..models import Quote, QuoteSample, Symbol, Watchlist, now
from ..schemas import QuoteResponse


def publish_quote(db: Session, quote: MarketQuote) -> None:
    """Future broker stream/worker ingestion point; timestamps are market timestamps."""
    if not quote.executable:
        return
    if quote.price_won <= 0 or quote.as_of.tzinfo is None:
        raise ValueError("Invalid market quote")
    # Retain a bounded tick history for the 10-minute behavior comparison.
    db.execute(
        insert(QuoteSample)
        .values(
            symbol=quote.symbol, price_won=quote.price_won, as_of=quote.as_of, source=quote.source
        )
        .on_conflict_do_nothing()
    )
    db.execute(delete(QuoteSample).where(QuoteSample.as_of < now() - timedelta(hours=24)))
    statement = insert(Quote).values(
        symbol=quote.symbol,
        price_won=quote.price_won,
        as_of=quote.as_of,
        sequence=1,
        source=quote.source,
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[Quote.symbol],
            set_={
                "price_won": statement.excluded.price_won,
                "as_of": statement.excluded.as_of,
                "source": statement.excluded.source,
                "sequence": Quote.sequence + 1,
            },
            where=or_(
                statement.excluded.as_of > Quote.as_of,
                and_(Quote.source == "demo", statement.excluded.source != "demo"),
                and_(
                    statement.excluded.as_of == Quote.as_of,
                    statement.excluded.source == Quote.source,
                    statement.excluded.price_won != Quote.price_won,
                ),
            ),
        )
    )


def snapshot(db: Session, user_id: str, provider: MarketDataPort) -> list[QuoteResponse]:
    symbols = db.scalars(
        select(Watchlist.symbol).where(Watchlist.user_id == user_id).order_by(Watchlist.symbol)
    ).all()
    for symbol in [] if isinstance(provider, StreamingMarketData) else symbols:
        try:
            quote = provider.get_quote(symbol)
        except BrokerNotConfigured:
            continue
        if quote is not None:
            publish_quote(db, quote)
    rows = db.execute(
        select(Symbol, Quote)
        .outerjoin(Quote, Quote.symbol == Symbol.symbol)
        .where(Symbol.symbol.in_(symbols))
        .order_by(Symbol.symbol)
    ).all()
    result = []
    for instrument, stored in rows:
        quote = stored
        if quote is not None and (
            (quote.source == "demo" and not isinstance(provider, DemoMarketData))
            or (isinstance(provider, StreamingMarketData) and quote.source != provider.source)
        ):
            quote = None
        if isinstance(provider, TossMarketData):
            display = provider.get_quote(instrument.symbol)
            if display is not None and (quote is None or display.as_of > quote.as_of):
                quote = display
        if quote is not None:
            result.append(
                QuoteResponse(
                    symbol=instrument.symbol,
                    name=instrument.name,
                    price_won=str(quote.price_won),
                    as_of=quote.as_of,
                    sequence=int(quote.as_of.timestamp() * 1_000_000)
                    if isinstance(provider, TossMarketData)
                    else quote.sequence,
                    source=quote.source,
                )
            )
    return result
