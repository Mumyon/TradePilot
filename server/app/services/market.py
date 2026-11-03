from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..brokers.contracts import BrokerNotConfigured, MarketDataPort, MarketQuote
from ..brokers.demo import DemoMarketData
from ..models import Quote, QuoteSample, Symbol, Watchlist, now
from ..schemas import QuoteResponse


def publish_quote(db: Session, quote: MarketQuote) -> None:
    """Future broker stream/worker ingestion point; timestamps are market timestamps."""
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
            where=statement.excluded.as_of > Quote.as_of,
        )
    )


def snapshot(db: Session, user_id: str, provider: MarketDataPort) -> list[QuoteResponse]:
    symbols = db.scalars(
        select(Watchlist.symbol).where(Watchlist.user_id == user_id).order_by(Watchlist.symbol)
    ).all()
    for symbol in symbols:
        try:
            quote = provider.get_quote(symbol)
        except BrokerNotConfigured:
            continue
        if quote is not None:
            publish_quote(db, quote)
    rows = db.execute(
        select(Quote, Symbol.name)
        .join(Symbol)
        .where(Quote.symbol.in_(symbols))
        .order_by(Quote.symbol)
    ).all()
    return [
        QuoteResponse(
            symbol=q.symbol,
            name=name,
            price_won=str(q.price_won),
            as_of=q.as_of,
            sequence=q.sequence,
            source=q.source,
        )
        for q, name in rows
        if q.source != "demo" or isinstance(provider, DemoMarketData)
    ]
