from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..models import Candle, now

SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
CHART_SECONDS = {**SECONDS, "3m": 180, "10m": 600, "30m": 1800}
KST = ZoneInfo("Asia/Seoul")


def chart_staleness(interval):
    if interval == "1w":
        return timedelta(days=10)
    if interval == "1mo":
        return timedelta(days=40)
    if interval == "1y":
        return timedelta(days=370)
    if interval == "1d":
        return timedelta(days=4)
    return timedelta(seconds=CHART_SECONDS[interval] * 2)


def aggregate_chart_candles(rows, interval, at, *, include_current=False):
    daily = interval in {"1d", "1w", "1mo", "1y"}
    groups = {}
    for row in rows:
        stamp = row["opened_at"]
        if daily:
            local = stamp.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
            if local.date() > at.astimezone(KST).date() or (
                not include_current and local.date() == at.astimezone(KST).date()
            ):
                continue
            if interval == "1w":
                start = local - timedelta(days=local.weekday())
                end = start + timedelta(days=7)
            elif interval == "1y":
                start = local.replace(month=1, day=1)
                end = start.replace(year=start.year + 1)
            elif interval == "1mo":
                start = local.replace(day=1)
                end = (start + timedelta(days=32)).replace(day=1)
            else:
                start, end = local, local + timedelta(days=1)
        else:
            seconds = CHART_SECONDS[interval]
            epoch = int(stamp.timestamp())
            start = datetime.fromtimestamp(epoch - epoch % seconds, UTC)
            end = start + timedelta(seconds=seconds)
        if end <= at or (include_current and start <= at < end and stamp <= at):
            groups.setdefault((start, end), {})[stamp] = row
    result = []
    for (start, end), group in sorted(groups.items()):
        stamps = sorted(group)
        complete = end <= at
        if (
            complete
            and not daily
            and stamps
            != [start + timedelta(minutes=i) for i in range(CHART_SECONDS[interval] // 60)]
        ):
            continue
        bars = [group[stamp] for stamp in stamps]
        as_of = end
        if not complete:
            as_of = at if daily else min(at, stamps[-1] + timedelta(minutes=1))
        result.append(
            dict(
                opened_at=start,
                closed_at=as_of,
                open_won=bars[0]["open_won"],
                high_won=max(bar["high_won"] for bar in bars),
                low_won=min(bar["low_won"] for bar in bars),
                close_won=bars[-1]["close_won"],
                volume=sum(bar["volume"] for bar in bars),
                source=bars[-1]["source"],
                complete=complete,
            )
        )
    return result


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
    if interval not in SECONDS:
        return dict(status="unavailable", interval=interval, source=None, stale=True, items=[])
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
    if mode in ("kis", "namuh"):
        query = query.where(Candle.source == provider.source)
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
