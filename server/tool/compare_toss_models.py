"""Compare fixed 1h candidates against a chronological Toss holdout."""

import argparse
import hashlib
import json
import math
from datetime import date
from importlib.metadata import version
from pathlib import Path
from statistics import mean

from catboost import CatBoostClassifier
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from app.ml.candidates import DEFAULT_MODELS, TEMPERATURES, fit_candidate, temperature_scale
from app.ml.experiment import evaluate, research_gate
from app.ml.pipeline import BAR, KST, read_csv, samples, validate_bars


def enriched_rows(bars):
    """Use only the 5m bar closed at the sample timestamp and its past."""
    history = {}
    segment = []
    for bar in bars:
        if segment and bar.opened_at - segment[-1].opened_at != BAR:
            segment = []
        segment.append(bar)
        if len(segment) < 35:
            continue
        local = bar.as_of.astimezone(KST)
        window_features = []
        for n in (3, 6, 12, 24):
            window = segment[-n:]
            changes = [math.log(b.close / b.open) for b in window]
            high, low = max(b.high for b in window), min(b.low for b in window)
            window_features.extend(
                (
                    math.log(bar.close / window[0].open),
                    math.sqrt(sum(change**2 for change in changes)),
                    (high - low) / bar.close,
                    (bar.close - low) / max(1, high - low),
                    math.log1p(mean(b.volume for b in window))
                    - math.log1p(mean(b.volume for b in segment)),
                )
            )
        history[bar.as_of] = [
            (local.hour * 60 + local.minute - 540) / 380,
            math.log(bar.close / segment[0].open),
            *window_features,
        ]
    return [{**row, "extended": [*row["x"], *history[row["as_of"]]]} for row in samples(bars)]


def extended_estimators(with_boosters):
    estimators = {
        "logistic-ohlcv": make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=400)),
        "balanced-logistic-ohlcv": make_pipeline(
            StandardScaler(), LogisticRegression(C=0.1, class_weight="balanced", max_iter=400)
        ),
        "hist-gradient-boosting-ohlcv": HistGradientBoostingClassifier(
            max_iter=160,
            max_leaf_nodes=7,
            min_samples_leaf=40,
            learning_rate=0.04,
            l2_regularization=2.0,
            early_stopping=False,
            random_state=42,
        ),
        "catboost-ohlcv": CatBoostClassifier(
            iterations=180,
            depth=4,
            learning_rate=0.04,
            l2_leaf_reg=5,
            has_time=True,
            bootstrap_type="No",
            random_seed=42,
            allow_writing_files=False,
            thread_count=1,
            verbose=False,
        ),
        "random-forest-ohlcv": RandomForestClassifier(
            n_estimators=240,
            max_depth=7,
            min_samples_leaf=24,
            n_jobs=1,
            random_state=42,
        ),
        "extra-trees-ohlcv": ExtraTreesClassifier(
            n_estimators=240,
            max_depth=8,
            min_samples_leaf=20,
            n_jobs=1,
            random_state=42,
        ),
        "knn-ohlcv": make_pipeline(
            StandardScaler(), KNeighborsClassifier(n_neighbors=75, weights="distance")
        ),
        "mlp-ohlcv": make_pipeline(
            StandardScaler(),
            MLPClassifier(
                hidden_layer_sizes=(24,),
                alpha=0.1,
                max_iter=140,
                random_state=42,
                early_stopping=False,
            ),
        ),
    }
    if with_boosters:
        from lightgbm import LGBMClassifier
        from xgboost import XGBClassifier

        estimators.update(
            {
                "lightgbm-ohlcv": LGBMClassifier(
                    n_estimators=180,
                    max_depth=4,
                    num_leaves=11,
                    learning_rate=0.04,
                    min_child_samples=40,
                    reg_lambda=3,
                    verbosity=-1,
                    random_state=42,
                    n_jobs=1,
                ),
                "xgboost-ohlcv": XGBClassifier(
                    n_estimators=180,
                    max_depth=3,
                    learning_rate=0.04,
                    min_child_weight=15,
                    reg_lambda=3,
                    eval_metric="mlogloss",
                    random_state=42,
                    n_jobs=1,
                ),
            }
        )
    return estimators


def compare(bars, cutoffs, *, with_boosters=False):
    validate_bars(bars)
    rows = enriched_rows(bars)
    calibration_start, selection_start, test_start = cutoffs

    def day(row, key):
        return row[key].astimezone(KST).date()

    training = [r for r in rows if day(r, "target_at") < calibration_start]
    calibration = [
        r
        for r in rows
        if calibration_start <= day(r, "as_of") and day(r, "target_at") < selection_start
    ]
    selection = [
        r for r in rows if selection_start <= day(r, "as_of") and day(r, "target_at") < test_start
    ]
    testing = [r for r in rows if day(r, "as_of") >= test_start]
    splits = dict(training=training, calibration=calibration, selection=selection, testing=testing)
    if any(len(group) < 100 or {r["y"] for r in group} != {0, 1, 2} for group in splits.values()):
        raise ValueError(
            f"Insufficient split data: { {name: len(group) for name, group in splits.items()} }"
        )
    prior = [sum(r["y"] == i for r in training) / len(training) for i in range(3)]
    validation_baseline = evaluate(selection, [prior] * len(selection))
    predictors = {name: fit_candidate(name, training).probabilities for name in DEFAULT_MODELS}
    x, y = [r["extended"] for r in training], [r["y"] for r in training]
    for name, estimator in extended_estimators(with_boosters).items():
        estimator.fit(x, y)
        predictors[name] = lambda part, model=estimator: model.predict_proba(
            [r["extended"] for r in part]
        ).tolist()

    def averaged(part):
        sources = [
            predictors[name](part)
            for name in (
                "logistic-ohlcv",
                "hist-gradient-boosting-ohlcv",
                "catboost-ohlcv",
                "extra-trees-ohlcv",
            )
        ]
        return [
            [mean(p[i] for p in group) for i in range(3)] for group in zip(*sources, strict=True)
        ]

    predictors["soft-vote-ohlcv"] = averaged
    candidates = {}
    for name, predict in predictors.items():
        raw = predict(calibration)
        temperature = min(
            TEMPERATURES,
            key=lambda t: evaluate(calibration, temperature_scale(raw, t))["log_loss"],
        )
        validation = evaluate(selection, temperature_scale(predict(selection), temperature))
        candidates[name] = dict(
            temperature=temperature,
            validation=validation,
            validation_gate=research_gate(validation, validation_baseline),
        )

    # Freeze the nominee before producing any holdout predictions.
    selected = max(
        candidates,
        key=lambda name: (
            candidates[name]["validation_gate"]["passed"],
            candidates[name]["validation"]["macro_f1"],
            -candidates[name]["validation"]["brier"],
        ),
    )
    baseline = evaluate(testing, [prior] * len(testing))
    for name, candidate in candidates.items():
        evaluated = evaluate(
            testing, temperature_scale(predictors[name](testing), candidate["temperature"])
        )
        candidate.update(test=evaluated, test_gate=research_gate(evaluated, baseline))
    return dict(
        bars=len(bars),
        data_start=bars[0].opened_at.isoformat(),
        data_end=bars[-1].as_of.isoformat(),
        splits={
            name: dict(
                count=len(group),
                start=group[0]["as_of"].isoformat(),
                end=group[-1]["target_at"].isoformat(),
            )
            for name, group in splits.items()
        },
        baseline=baseline,
        candidates=candidates,
        selected_before_holdout=selected,
        confirmed_model=selected if candidates[selected]["test_gate"]["passed"] else None,
        other_holdout_passes=[
            name
            for name, candidate in candidates.items()
            if name != selected and candidate["test_gate"]["passed"]
        ],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extended-boosters", action="store_true")
    args = parser.parse_args()
    # All dates precede the Samsung July 22 dataset used in the earlier comparison.
    cutoffs = (date(2026, 4, 27), date(2026, 5, 18), date(2026, 6, 8))
    report = dict(
        source="Toss Open API completed 5m OHLCV",
        cutoff_dates_kst=[str(day) for day in cutoffs],
        horizon_minutes=60,
        threshold_percent=0.5,
        confidence_threshold=0.65,
        source_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        packages={
            name: version(name)
            for name in (
                "scikit-learn",
                "catboost",
                "numpy",
                *(("lightgbm", "xgboost") if args.extended_boosters else ()),
            )
        },
        symbols={},
    )
    with threadpool_limits(limits=1):
        for symbol in ("005930", "000660"):
            files = sorted(args.data.glob(f"{symbol}-*.csv"))
            bars = [bar for file in files for bar in read_csv(file)]
            if (
                not bars
                or bars[0].opened_at.astimezone(KST).date() != date(2026, 2, 2)
                or bars[-1].opened_at.astimezone(KST).date() != date(2026, 7, 21)
            ):
                raise ValueError(f"{symbol}: missing the fixed February–July data range")
            report["symbols"][symbol] = compare(bars, cutoffs, with_boosters=args.extended_boosters)
            report["symbols"][symbol]["input_sha256"] = {
                file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in files
            }
            result = report["symbols"][symbol]
            print(
                symbol,
                "nominee",
                result["selected_before_holdout"],
                "confirmed",
                result["confirmed_model"],
                "other passes",
                result["other_holdout_passes"],
                flush=True,
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)


if __name__ == "__main__":
    main()
