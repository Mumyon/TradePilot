"""Summarize anonymous human survey input; never generates participants or ratings."""

import argparse
import csv
import json
from pathlib import Path
from statistics import mean


def summarize(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    ids = set()
    scores = []
    completed = 0
    for row in rows:
        ident = row["participant_id"].strip()
        if not ident or ident in ids:
            raise ValueError("Participant IDs must be nonempty and unique")
        ids.add(ident)
        values = [int(row[key]) for key in ("clarity_rating", "ease_rating", "overall_rating")]
        if any(v < 1 or v > 5 for v in values) or row["completed_core_flow"] not in ("yes", "no"):
            raise ValueError("Ratings must be 1..5, completed_core_flow must be yes/no")
        scores.append(values[-1])
        completed += row["completed_core_flow"] == "yes"
    return dict(
        participants=len(rows),
        completed=completed,
        overall_mean=mean(scores) if scores else None,
        target_met=len(rows) >= 10 and mean(scores) >= 4,
        status="awaiting_participants" if not rows else "collected",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    args = parser.parse_args()
    print(json.dumps(summarize(args.csv), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
