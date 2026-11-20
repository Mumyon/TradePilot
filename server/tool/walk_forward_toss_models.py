"""Repeat fixed 1h prediction experiments on non-overlapping test dates."""

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
from catboost import CatBoostClassifier
from scipy.special import softmax
from scipy.stats import t as student_t
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from threadpoolctl import threadpool_limits

from app.ml.candidates import TEMPERATURES, ordered_probabilities, temperature_scale
from app.ml.experiment import evaluate, research_gate
from app.ml.pipeline import KST, feature_rows, read_csv, validate_bars
from tool.compare_toss_models import enriched_rows

SYMBOLS = ("005930", "000660")
LOWER, UPPER = 100 * np.log([0.995, 1.005])
TRAIN_DAYS, CALIBRATION_DAYS, SELECTION_DAYS, TEST_DAYS = 26, 8, 8, 10


def trading_date(stamp):
    return stamp.astimezone(KST).date()


def rocket_features(windows):
    """Fixed random convolution features using the ROCKET max/positive summaries."""
    random = np.random.default_rng(2704)
    columns = []
    for _ in range(96):
        channel = int(random.integers(windows.shape[1]))
        kernel_size = int(random.choice([3, 5, 7]))
        dilation = int(random.choice([1, 2, 3]))
        weights = random.normal(size=kernel_size)
        weights -= weights.mean()
        width = (kernel_size - 1) * dilation + 1
        window = np.lib.stride_tricks.sliding_window_view(windows[:, channel], width, axis=1)
        result = window[:, :, ::dilation] @ weights + random.uniform(-1, 1)
        columns.extend((result.max(axis=1), (result > 0).mean(axis=1)))
    return np.column_stack(columns)


def prepare(bars, peer_bars):
    validate_bars(bars)
    validate_bars(peer_bars)
    rows = enriched_rows(bars)
    peer = {row["as_of"]: row["x"] for row in feature_rows(peer_bars)}
    index = {bar.as_of: i for i, bar in enumerate(bars)}
    selected, features, paths, future, volatility = [], [], [], [], []
    for row in rows:
        paired = peer.get(row["as_of"])
        if paired is None:
            continue
        at = index[row["as_of"]]
        target = index[row["target_at"]]
        window = bars[at - 24 : at + 1]
        prices = np.log([bar.close for bar in window])
        returns = np.diff(prices) * 100
        vol = max(0.025, np.sqrt(np.mean(returns**2)))
        volumes = np.log1p([bar.volume for bar in window[1:]])
        features.append(
            [
                *row["extended"],
                *paired,
                *(own - other for own, other in zip(row["x"], paired, strict=True)),
            ]
        )
        paths.append([returns / vol, volumes - np.mean(volumes)])
        future.append(100 * np.log(bars[target].close / row["price"]))
        volatility.append(vol * np.sqrt(12))
        selected.append(row)
    return (
        selected,
        np.array(features),
        rocket_features(np.array(paths)),
        np.array(future),
        np.array(volatility),
    )


def logistic(**kwargs):
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=350, C=0.15, **kwargs))


def candidate_probabilities(features, rocket, returns, volatility, labels, train, future):
    x, y = features[train], labels[train]
    prediction = features[future]
    candidates = {}

    estimators = {
        "cross-stock-logistic": logistic(),
        "cross-stock-catboost": CatBoostClassifier(
            iterations=110,
            depth=4,
            learning_rate=0.045,
            l2_leaf_reg=5,
            has_time=True,
            bootstrap_type="No",
            random_seed=42,
            thread_count=1,
            verbose=False,
            allow_writing_files=False,
        ),
        "historical-neighbors": make_pipeline(
            StandardScaler(), KNeighborsClassifier(n_neighbors=70, weights="distance")
        ),
    }
    for name, estimator in estimators.items():
        candidates[name] = estimator.fit(x, y).predict_proba(prediction)

    kernel = make_pipeline(StandardScaler(), SVC(C=0.35, gamma="scale"))
    scores = kernel.fit(x, y).decision_function(prediction)
    candidates["rbf-svm"] = softmax(scores, axis=1)

    combined = np.column_stack((features, rocket))
    candidates["random-convolution"] = (
        logistic().fit(combined[train], y).predict_proba(combined[future])
    )

    move = (y != 1).astype(int)
    direction = (y[move == 1] == 0).astype(int)
    move_probability = logistic().fit(x, move).predict_proba(prediction)[:, 1]
    up_given_move = logistic().fit(x[move == 1], direction).predict_proba(prediction)[:, 1]
    candidates["move-then-direction"] = np.column_stack(
        (
            move_probability * up_given_move,
            1 - move_probability,
            move_probability * (1 - up_given_move),
        )
    )

    quantiles = np.array([0.05, 0.15, 0.30, 0.50, 0.70, 0.85, 0.95])
    quantile_returns = []
    for quantile in quantiles:
        model = HistGradientBoostingRegressor(
            loss="quantile",
            quantile=quantile,
            max_iter=52,
            max_leaf_nodes=7,
            min_samples_leaf=36,
            l2_regularization=2,
            early_stopping=False,
            random_state=42,
        )
        quantile_returns.append(model.fit(x, returns[train]).predict(prediction))
    ordered = np.sort(np.column_stack(quantile_returns), axis=1)
    down, up = np.array(
        [[np.interp(LOWER, q, quantiles), 1 - np.interp(UPPER, q, quantiles)] for q in ordered]
    ).T
    candidates["boosted-quantile-returns"] = np.column_stack((up, 1 - up - down, down))

    ridge = make_pipeline(StandardScaler(), Ridge(alpha=120))
    normalized = returns / volatility
    ridge.fit(x, normalized[train])
    dof, location, scale = student_t.fit(normalized[train] - ridge.predict(x))
    mean = ridge.predict(prediction) + location
    down = student_t.cdf((LOWER / volatility[future] - mean) / scale, dof)
    up = student_t.sf((UPPER / volatility[future] - mean) / scale, dof)
    candidates["student-t-return-regression"] = np.column_stack((up, 1 - up - down, down))
    candidates["soft-vote"] = np.mean(
        [
            candidates[name]
            for name in (
                "cross-stock-catboost",
                "move-then-direction",
                "random-convolution",
                "student-t-return-regression",
            )
        ],
        axis=0,
    )
    return candidates


def directional_reliability(rows, probabilities):
    """Count at most one signal per hour and resample complete trading days."""
    by_day = defaultdict(list)
    next_origin = rows[0]["as_of"]
    for row, values in zip(rows, probabilities, strict=True):
        decision = int(np.argmax(values))
        if decision == 1 or values[decision] < 0.65 or row["as_of"] < next_origin:
            continue
        by_day[trading_date(row["as_of"])].append(int(decision == row["y"]))
        next_origin = row["target_at"]
    hits = sum(sum(outcomes) for outcomes in by_day.values())
    count = sum(map(len, by_day.values()))
    lower = None
    if len(by_day) >= 5:
        random = np.random.default_rng(91)
        sample = random.integers(len(by_day), size=(2000, len(by_day)))
        lengths = np.array([len(values) for values in by_day.values()])
        scores = np.array([sum(values) for values in by_day.values()])
        lower = float(np.quantile(scores[sample].sum(axis=1) / lengths[sample].sum(axis=1), 0.025))
    return dict(
        signals=count,
        hits=hits,
        signal_days=len(by_day),
        accuracy=hits / count if count else None,
        day_bootstrap_lower_95=lower,
        reliable=count >= 20 and lower is not None and lower > 0.5,
    )


def walk_forward(data, *, extra_candidates=None, test_start=None):
    rows, features, rocket, returns, volatility = data
    labels = np.array([row["y"] for row in rows])
    row_days = np.array([trading_date(row["as_of"]) for row in rows])
    days = sorted(set(row_days))
    offset = TRAIN_DAYS + CALIBRATION_DAYS + SELECTION_DAYS
    folds, evaluation_rows, all_probabilities = [], [], defaultdict(list)
    first_test = next(
        (i for i in range(offset, len(days)) if test_start is None or days[i] >= test_start),
        len(days),
    )
    for end in range(first_test, len(days) - TEST_DAYS + 1, TEST_DAYS):
        days_in_fold = days[end - offset : end + TEST_DAYS]
        parts = np.split(days_in_fold, [TRAIN_DAYS, TRAIN_DAYS + CALIBRATION_DAYS, offset])
        train, calibration, selection, test = [
            np.flatnonzero(np.isin(row_days, part)) for part in parts
        ]
        # Only training requires every class for the estimators. Filtering other
        # periods by their realized labels would bias out-of-sample evaluation.
        if any(len(part) < 80 for part in (train, calibration, selection, test)):
            continue
        if set(labels[train]) != {0, 1, 2}:
            continue
        assert all(
            rows[left[-1]]["target_at"] < rows[right[0]]["as_of"]
            for left, right in zip(
                (train, calibration, selection), (calibration, selection, test), strict=True
            )
        )
        test_rows = [rows[i] for i in test]
        calibration_rows = [rows[i] for i in calibration]
        selection_rows = [rows[i] for i in selection]
        evaluation_rows.extend(test_rows)
        prior = (np.bincount(labels[train], minlength=3) / len(train)).tolist()
        baseline = evaluate(test_rows, [prior] * len(test))
        selection_baseline = evaluate(selection_rows, [prior] * len(selection))
        all_probabilities["baseline"].extend([prior] * len(test))
        future = np.concatenate((calibration, selection, test))
        candidates, reports = {}, {}
        predictions = candidate_probabilities(
            features, rocket, returns, volatility, labels, train, future
        )
        if extra_candidates is not None:
            predictions.update(extra_candidates(rows, train, future, prior, predictions))
        for name, raw in predictions.items():
            if not np.isfinite(raw).all() or np.any((raw < -1e-10) | (raw > 1 + 1e-10)):
                raise ValueError(f"{name}: invalid probabilities")
            probabilities = ordered_probabilities(np.clip(raw, 0, 1), [0, 1, 2])
            selection_end = len(calibration) + len(selection)
            cal = probabilities[: len(calibration)]
            select = probabilities[len(calibration) : selection_end]
            held = probabilities[selection_end:]
            temperature = min(
                TEMPERATURES,
                key=lambda t: evaluate(calibration_rows, temperature_scale(cal, t))["log_loss"],
            )
            validation = evaluate(selection_rows, temperature_scale(select, temperature))
            candidates[name] = (
                research_gate(validation, selection_baseline)["passed"],
                validation["macro_f1"],
                -validation["brier"],
                temperature_scale(held, temperature),
            )
        nominee = max(candidates, key=lambda name: candidates[name][:3])
        all_probabilities["validation-selected"].extend(candidates[nominee][3])
        for name, (*_, probabilities) in candidates.items():
            all_probabilities[name].extend(probabilities)
            result = evaluate(test_rows, probabilities)
            reports[name] = dict(
                macro_f1=result["macro_f1"],
                brier=result["brier"],
                gate_passed=research_gate(result, baseline)["passed"],
                directional=directional_reliability(test_rows, probabilities),
            )
        folds.append(
            dict(
                start=str(parts[-1][0]),
                end=str(parts[-1][-1]),
                samples=len(test),
                nominee=nominee,
                models=reports,
            )
        )
    if not folds:
        raise ValueError("Not enough completed trading days for walk-forward")
    baseline = evaluate(evaluation_rows, all_probabilities.pop("baseline"))
    models = {}
    for name, probabilities in all_probabilities.items():
        result = evaluate(evaluation_rows, probabilities)
        models[name] = dict(
            test=result,
            gate=research_gate(result, baseline),
            directional=directional_reliability(evaluation_rows, probabilities),
        )
    return dict(folds=folds, baseline=baseline, models=models)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--test-start", type=date.fromisoformat, help="Earliest eligible test trading date"
    )
    parser.add_argument(
        "--adaptive-prior",
        action="store_true",
        help="Also evaluate existing recent-outcome probability adjustments",
    )
    args = parser.parse_args()
    extra_candidates = None
    if args.adaptive_prior:
        from tool.compare_market_context import adaptive_candidates

        extra_candidates = adaptive_candidates
    files = {
        symbol: sorted(path for folder in args.data for path in folder.glob(f"{symbol}-*.csv"))
        for symbol in SYMBOLS
    }
    bars = {
        symbol: sorted([bar for path in paths for bar in read_csv(path)], key=lambda b: b.opened_at)
        for symbol, paths in files.items()
    }
    report = dict(
        label=args.label,
        source="Toss Open API completed 5m OHLCV",
        horizon_minutes=60,
        threshold_percent=0.5,
        confidence_threshold=0.65,
        evaluation_policy="All sufficiently populated test windows, regardless of test labels",
        data_status=(
            f"Test windows starting on or after {args.test_start}"
            if args.test_start
            else "Previously inspected historical data; exploratory repeat evaluation"
        ),
        adaptive_prior=args.adaptive_prior,
        adaptive_source_sha256=(
            hashlib.sha256(
                Path(__file__).with_name("compare_market_context.py").read_bytes()
            ).hexdigest()
            if args.adaptive_prior
            else None
        ),
        source_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        windows=dict(
            train=TRAIN_DAYS, calibration=CALIBRATION_DAYS, selection=SELECTION_DAYS, test=TEST_DAYS
        ),
        symbols={},
    )
    with threadpool_limits(limits=1):
        for symbol, peer in (SYMBOLS, SYMBOLS[::-1]):
            print(f"{symbol}: {len(bars[symbol])} completed bars", flush=True)
            result = walk_forward(
                prepare(bars[symbol], bars[peer]),
                extra_candidates=extra_candidates,
                test_start=args.test_start,
            )
            result["data_start"] = bars[symbol][0].opened_at.isoformat()
            result["data_end"] = bars[symbol][-1].as_of.isoformat()
            result["input_sha256"] = {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files[symbol]
            }
            report["symbols"][symbol] = result
            print(f"{symbol}: {len(result['folds'])} test windows", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(serialized)


if __name__ == "__main__":
    main()
