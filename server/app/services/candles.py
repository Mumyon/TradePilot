from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..models import Candle, now

SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}


def ingest(db, symbol, interval, rows):
    for row in rows:
        stamp = row["opened_at"]
        values = [row[k] for k in ("open_won", "high_won", "low_won", "close_won")]
        if (
            interval not in SECONDS
            or stamp.tzinfo is None
            or stamp > now()
            or (row["complete"] and stamp + timedelta(seconds=SECONDS[interval]) > now())
            or min(values) <= 0
            or row["low_won"] > min(row["open_won"], row["close_won"])
            or row["high_won"] < max(row["open_won"], row["close_won"])
            or row["volume"] < 0
        ):
            raise ValueError("Invalid OHLCV")
        item = dict(row, symbol=symbol, interval=interval)
        statement = insert(Candle).values(**item)
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[Candle.symbol, Candle.interval, Candle.opened_at, Candle.source],
                set_={
                    k: getattr(statement.excluded, k)
                    for k in ["open_won", "high_won", "low_won", "close_won", "volume", "complete"]
                },
                where=~Candle.complete,
            )
        )


def history(db, symbol, interval, provider, mode):
    if mode == "demo":
        ingest(db, symbol, interval, provider.get_candles(symbol, interval))
    query = select(Candle).where(
        Candle.symbol == symbol,
        Candle.interval == interval,
        Candle.complete.is_(True),
        Candle.opened_at <= now() - timedelta(seconds=SECONDS[interval]),
    )
    query = (
        query.where(Candle.source == "demo")
        if mode == "demo"
        else query.where(Candle.source != "demo")
    )
    latest_source = db.scalar(query.order_by(Candle.opened_at.desc(), Candle.source).limit(1))
    if latest_source is not None:
        query = query.where(Candle.source == latest_source.source)
    rows = list(reversed(db.scalars(query.order_by(Candle.opened_at.desc()).limit(120)).all()))
    latest = rows[-1] if rows else None
    stale = latest is None or now() - latest.opened_at > timedelta(seconds=SECONDS[interval] * 2)
    return dict(
        status="available" if rows else "unavailable",
        interval=interval,
        source=latest.source if latest else None,
        stale=stale,
        as_of=latest.opened_at + timedelta(seconds=SECONDS[interval]) if latest else None,
        items=[
            dict(
                opened_at=c.opened_at,
                open_won=str(c.open_won),
                high_won=str(c.high_won),
                low_won=str(c.low_won),
                close_won=str(c.close_won),
                volume=c.volume,
                complete=c.complete,
                source=c.source,
            )
            for c in rows
        ],
    )


def demo_candles(symbol, interval):
    base = {"005930": 72800, "000660": 173500}.get(symbol)
    if base is None:
        return []
    seconds = SECONDS[interval]
    end = int(now().timestamp()) // seconds * seconds
    result = []
    for i in range(120, 0, -1):
        stamp = end - i * seconds
        phase = stamp // seconds
        opening = base + ((phase % 13) - 6) * 50
        closing = base + (((phase + 1) % 13) - 6) * 50
        result.append(
            dict(
                opened_at=datetime.fromtimestamp(stamp, UTC),
                open_won=opening,
                high_won=max(opening, closing) + 100,
                low_won=min(opening, closing) - 100,
                close_won=closing,
                volume=1000 + (phase % 17) * 100,
                complete=True,
                source="demo",
            )
        )
    return result
