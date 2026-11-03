"""Offline CSV training/import. Never downloads data or enables a model automatically."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from ..config import Settings
from ..db import make_database
from ..models import Symbol, now
from ..services.candles import ingest
from .pipeline import read_csv, train


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["train", "import-candles"])
    parser.add_argument("--csv", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--data-kind", choices=["historical", "synthetic"], required=True)
    parser.add_argument("--output", default="models/predictor.json")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Z0-9.]{1,16}", args.symbol) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,32}", args.source
    ):
        parser.error("Invalid symbol/source identifier")
    if args.data_kind == "historical" and args.source in ["demo", "synthetic"]:
        parser.error("Synthetic source cannot be declared historical")
    bars = read_csv(args.csv)
    if not bars or bars[-1].as_of > now():
        parser.error("CSV is empty or contains unfinished/future bars")
    if args.command == "train":
        artifact = train(
            bars,
            args.symbol,
            args.source,
            args.data_kind,
            hashlib.sha256(Path(args.csv).read_bytes()).hexdigest(),
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False))
        temporary.replace(output)
        print(
            json.dumps(
                dict(
                    output=str(output),
                    version=artifact["version"],
                    data_kind=args.data_kind,
                    quality_gate_passed=artifact["quality_gate_passed"],
                    test=artifact["evaluation"]["test"],
                    baseline=artifact["evaluation"]["baseline"],
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        engine, sessions = make_database(Settings().database_url.get_secret_value())
        try:
            with sessions.begin() as db:
                if db.get(Symbol, args.symbol) is None:
                    db.add(Symbol(symbol=args.symbol, name=args.symbol))
                    db.flush()
                ingest(
                    db,
                    args.symbol,
                    "5m",
                    [
                        dict(
                            opened_at=b.opened_at,
                            open_won=b.open,
                            high_won=b.high,
                            low_won=b.low,
                            close_won=b.close,
                            volume=b.volume,
                            complete=True,
                            source=args.source,
                        )
                        for b in bars
                    ],
                )
            print(
                f"Imported {len(bars)} completed bars; source={args.source}; kind={args.data_kind}"
            )
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
