"""Test pinned Chronos-Bolt weights on the same 1h walk-forward windows."""

import argparse
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import numpy as np
import torch
from chronos import BaseChronosPipeline

from app.ml.candidates import TEMPERATURES, ordered_probabilities, temperature_scale
from app.ml.experiment import evaluate, research_gate
from app.ml.pipeline import BAR, feature_rows, read_csv, samples, validate_bars
from tool.walk_forward_toss_models import (
    CALIBRATION_DAYS,
    SELECTION_DAYS,
    SYMBOLS,
    TEST_DAYS,
    TRAIN_DAYS,
    directional_reliability,
    trading_date,
)

REVISION = "f6ff2d2ba9168d498c015bc8dd07e3b395b31b3f"
QUANTILES = [i / 10 for i in range(1, 10)]


def contexts(bars, peer):
    validate_bars(bars)
    validate_bars(peer)
    available = {r["as_of"] for r in feature_rows(peer)}
    rows = [r for r in samples(bars) if r["as_of"] in available]
    history = {}
    segment = []
    previous = None
    for bar in bars:
        if previous is None or bar.opened_at - previous != BAR:
            segment = []
        segment.append(bar.close)
        history[bar.as_of] = segment[-60:]
        previous = bar.opened_at
    return rows, [history[r["as_of"]] for r in rows]


def forecast(pipeline, history, *, log_prices):
    limits = 100 * np.log([0.995, 1.005]) if log_prices else [-0.5, 0.5]
    result = []
    for start in range(0, len(history), 96):
        inputs = []
        for window in history[start : start + 96]:
            ratio = np.array(window) / window[-1]
            values = 100 * np.log(ratio) if log_prices else 100 * (ratio - 1)
            inputs.append(torch.tensor(values, dtype=torch.float32))
        values, _ = pipeline.predict_quantiles(
            inputs, prediction_length=12, quantile_levels=QUANTILES
        )
        for q in np.sort(values[:, -1, :].float().cpu().numpy(), axis=1):
            down, middle_upper = np.interp(limits, q, QUANTILES)
            result.append([1 - middle_upper, middle_upper - down, down])
    return ordered_probabilities(result, [0, 1, 2])


def evaluate_windows(rows, raw):
    day = np.array([trading_date(r["as_of"]) for r in rows])
    days = sorted(set(day))
    labels = np.array([r["y"] for r in rows])
    offset = TRAIN_DAYS + CALIBRATION_DAYS + SELECTION_DAYS
    folds, test_rows, calibrated, zero_shot, priors = [], [], [], [], []
    for end in range(offset, len(days) - TEST_DAYS + 1, TEST_DAYS):
        train, calibration, selection, test = [
            np.flatnonzero(np.isin(day, period))
            for period in np.split(
                days[end - offset : end + TEST_DAYS],
                [TRAIN_DAYS, TRAIN_DAYS + CALIBRATION_DAYS, offset],
            )
        ]
        if any(
            len(part) < 80 or set(labels[part]) != {0, 1, 2}
            for part in (train, calibration, selection, test)
        ):
            continue
        calibration_rows = [rows[i] for i in calibration]
        test_part = [rows[i] for i in test]
        cal_probs = [raw[i] for i in calibration]
        test_probs = [raw[i] for i in test]
        temperature = min(
            TEMPERATURES,
            key=lambda t: evaluate(calibration_rows, temperature_scale(cal_probs, t))["log_loss"],
        )
        test_rows.extend(test_part)
        zero_shot.extend(test_probs)
        calibrated.extend(temperature_scale(test_probs, temperature))
        prior = (np.bincount(labels[train], minlength=3) / len(train)).tolist()
        priors.extend([prior] * len(test))
        folds.append(
            dict(
                start=str(day[test[0]]),
                end=str(day[test[-1]]),
                samples=len(test),
                temperature=temperature,
            )
        )
    if not folds:
        raise ValueError("No complete test windows")
    baseline = evaluate(test_rows, priors)
    results = {}
    for name, probabilities in (("zero-shot", zero_shot), ("temperature-calibrated", calibrated)):
        result = evaluate(test_rows, probabilities)
        results[name] = dict(
            test=result,
            gate=research_gate(result, baseline),
            directional=directional_reliability(test_rows, probabilities),
        )
    return dict(folds=folds, baseline=baseline, models=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--data", required=True, type=Path, nargs="+")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    pipeline = BaseChronosPipeline.from_pretrained(
        args.model,
        device_map="cpu",
        local_files_only=True,
        torch_dtype=torch.float32,
    )
    files = {
        symbol: sorted(path for folder in args.data for path in folder.glob(f"{symbol}-*.csv"))
        for symbol in SYMBOLS
    }
    bars = {
        symbol: sorted([b for p in paths for b in read_csv(p)], key=lambda b: b.opened_at)
        for symbol, paths in files.items()
    }
    report = dict(
        model="amazon/chronos-bolt-tiny",
        revision=REVISION,
        model_sha256=hashlib.file_digest(
            (args.model / "model.safetensors").open("rb"), "sha256"
        ).hexdigest(),
        packages={p: version(p) for p in ("chronos-forecasting", "torch", "transformers")},
        symbols={},
    )
    for symbol, peer in (SYMBOLS, SYMBOLS[::-1]):
        rows, history = contexts(bars[symbol], bars[peer])
        report["symbols"][symbol] = {}
        for name in ("rebased-price", "rebased-log-price"):
            raw = forecast(pipeline, history, log_prices=name.endswith("log-price"))
            report["symbols"][symbol][name] = evaluate_windows(rows, raw)
            print(symbol, name, len(rows), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(serialized)


if __name__ == "__main__":
    main()
