"""Test the same random forest with and without a lower Bollinger band entry filter."""

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from statistics import mean, pstdev

import numpy as np
from sklearn.ensemble import RandomForestClassifier

from app.ml.candidates import TEMPERATURES, temperature_scale
from app.ml.experiment import evaluate, research_gate
from app.ml.pipeline import BAR, read_csv, validate_bars
from tool.compare_toss_models import enriched_rows
from tool.walk_forward_toss_models import SYMBOLS, directional_reliability, trading_date


def bollinger_features(prior_closes, current):
    center = mean(prior_closes)
    spread = pstdev(prior_closes)
    return (
        4 * spread / center,
        (current.close - center) / center,
        current.low <= center - 2 * spread,
    )


def samples(bars):
    validate_bars(bars)
    positions = {b.as_of: i for i, b in enumerate(bars)}
    for row in enriched_rows(bars):
        i = positions[row["as_of"]]
        window = bars[i - 20 : i]
        if len(window) != 20 or bars[i].opened_at - window[0].opened_at != 20 * BAR:
            continue
        width, deviation, touch = bollinger_features([b.close for b in window], bars[i])
        yield dict(row, x=[*row["extended"], width, deviation], touch=touch)


def compare(rows, cutoff):
    row_days = np.array([trading_date(row["as_of"]) for row in rows])
    days = sorted(set(row_days))
    x, y = np.array([r["x"] for r in rows]), np.array([r["y"] for r in rows])
    observed, predictions, priors, windows = [], [], [], []
    first = next((i for i, day in enumerate(days) if i >= 42 and day >= cutoff), len(days))
    for end in range(first, len(days) - 9, 10):
        parts = np.split(days[end - 42 : end + 10], [26, 34, 42])
        train, cal, reserved, test = (np.flatnonzero(np.isin(row_days, part)) for part in parts)
        if min(map(len, (train, cal, reserved, test))) < 80 or set(y[train]) != {0, 1, 2}:
            continue
        assert all(
            rows[left[-1]]["target_at"] < rows[right[0]]["as_of"]
            for left, right in zip((train, cal, reserved), (cal, reserved, test), strict=True)
        )
        forest = RandomForestClassifier(
            n_estimators=240, max_depth=6, min_samples_leaf=20, random_state=91, n_jobs=1
        ).fit(x[train], y[train])
        cal_raw = forest.predict_proba(x[cal])
        cal_rows = [rows[i] for i in cal]
        temperature = min(
            TEMPERATURES,
            key=lambda t: evaluate(cal_rows, temperature_scale(cal_raw, t))["log_loss"],
        )
        observed.extend(rows[i] for i in test)
        predictions.extend(temperature_scale(forest.predict_proba(x[test]), temperature))
        priors.extend([(np.bincount(y[train], minlength=3) / len(train)).tolist()] * len(test))
        windows.append(dict(start=str(parts[-1][0]), end=str(parts[-1][-1]), samples=len(test)))
    if not observed:
        raise ValueError("No complete test windows after cutoff")
    results = {}
    for name, indexes in {
        "all": list(range(len(observed))),
        "lower_band_touch": [i for i, row in enumerate(observed) if row["touch"]],
    }.items():
        if not indexes:
            results[name] = dict(eligible=0, passed=False)
            continue
        sample = [observed[i] for i in indexes]
        forecast = [[float(value) for value in predictions[i]] for i in indexes]
        metrics = evaluate(sample, forecast)
        baseline = evaluate(sample, [priors[i] for i in indexes])
        gate = research_gate(metrics, baseline)
        directional = directional_reliability(sample, forecast)
        results[name] = dict(
            eligible=len(sample),
            coverage=len(sample) / len(observed),
            metrics=metrics,
            baseline=baseline,
            gate=gate,
            directional=directional,
            passed=gate["passed"] and directional["reliable"],
        )
    return dict(windows=windows, results=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, nargs="+", required=True)
    parser.add_argument("--test-start", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = dict(
        test_start=str(args.test_start),
        evaluation="Exploratory comparison on previously inspected test dates",
        label="60 minutes, +/-0.5%; signal confidence >=65%",
        filter="Current completed bar low <= prior 20 closes SMA minus 2 population SD",
        symbols={},
    )
    for symbol in SYMBOLS:
        files = sorted(f for folder in args.data for f in folder.glob(f"{symbol}-*.csv"))
        bars = sorted((b for f in files for b in read_csv(f)), key=lambda bar: bar.opened_at)
        result = compare(list(samples(bars)), args.test_start)
        result["input_sha256"] = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
        report["symbols"][symbol] = result
        print(symbol, len(result["windows"]), "test windows", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, indent=2, allow_nan=False)
    with args.output.open("x") as output:
        output.write(serialized)


if __name__ == "__main__":
    main()
