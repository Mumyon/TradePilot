"""Train and evaluate the existing 1h model on completed Toss candles."""

import argparse
import hashlib
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from app.brokers.toss import SOURCE, TossMarketData, TossUnavailable, complete_five_minute_candles
from app.config import Settings
from app.ml.pipeline import KST, Bar, train


def historical_bars(provider, symbol, start, end):
    result = []
    day = start
    while day <= end:
        opening = datetime.combine(day, datetime.min.time(), KST).replace(hour=9)
        closing = opening + timedelta(hours=6, minutes=20)
        day += timedelta(days=1)
        if opening.weekday() >= 5:
            continue
        before = closing - timedelta(minutes=1)
        minutes = []
        while before >= opening:
            time.sleep(0.25)
            try:
                page = provider.get_candles(symbol, "1m", before=before)
            except TossUnavailable as exc:
                if "HTTP 429" not in str(exc):
                    raise
                time.sleep(2)
                page = provider.get_candles(symbol, "1m", before=before)
            if not page or page[-1]["opened_at"] < opening:
                break
            minutes.extend(row for row in page if opening <= row["opened_at"] <= before)
            next_before = page[0]["opened_at"] - timedelta(minutes=1)
            if next_before >= before:
                raise ValueError("Toss historical pagination did not advance")
            before = next_before
        result.extend(
            Bar(
                row["opened_at"],
                row["open_won"],
                row["high_won"],
                row["low_won"],
                row["close_won"],
                row["volume"],
            )
            for row in complete_five_minute_candles(minutes)
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", choices=["005930", "000660"], required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.start <= args.end < datetime.now(KST).date():
        parser.error("Use past trading dates only")
    provider = TossMarketData(Settings(database_url="postgresql://unused"))
    try:
        bars = historical_bars(provider, args.symbol, args.start, args.end)
    except TossUnavailable as exc:
        parser.exit(1, f"{exc}\n")
    print(f"{args.symbol}: {len(bars)} completed bars", flush=True)
    checksum = hashlib.sha256(
        json.dumps(
            [[b.opened_at.isoformat(), b.open, b.high, b.low, b.close, b.volume] for b in bars],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    artifact = train(bars, args.symbol, SOURCE, "historical", checksum, strict=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(artifact, output, ensure_ascii=False, indent=2, allow_nan=False)
    print(
        json.dumps(
            {
                key: artifact[key]
                for key in ("data_start", "data_end", "quality_gate_passed", "evaluation")
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
