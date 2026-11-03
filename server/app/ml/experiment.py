"""Offline model comparison; validation selection, sealed chronological test report.

Reports are research evidence, not deployable models. No automatic activation.
"""

import argparse
import hashlib
import json
import platform
from collections import Counter
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .candidates import DEFAULT_MODELS, TEMPERATURES, fit_candidate, temperature_scale
from .pipeline import FEATURES, KST, LABELS, metrics, read_csv, samples, validate_bars


def quality_report(bars):
    validate_bars(bars)
    if not bars:
        raise ValueError("Empty dataset")
    if bars[-1].as_of > datetime.now(UTC):
        raise ValueError("Future or unfinished bar")
    days = {}
    for bar in bars:
        day = bar.opened_at.astimezone(KST).date().isoformat()
        days.setdefault(day, set()).add(bar.opened_at.astimezone(KST).strftime("%H:%M"))
    expected = [
        (datetime(2000, 1, 1, 9) + timedelta(minutes=5 * i)).strftime("%H:%M") for i in range(78)
    ]
    rows = samples(bars)
    return dict(
        bars=len(bars),
        labeled_samples=len(rows),
        observed_days=len(days),
        zero_volume_bars=sum(b.volume == 0 for b in bars),
        class_counts=dict(Counter(LABELS[r["y"]] for r in rows)),
        sessions=[
            dict(
                date=d,
                observed=len(times),
                missing_open_times=[t for t in expected if t not in times],
            )
            for d, times in sorted(days.items())
        ],
        limitations=[
            "Observed dates only; exchange holiday calendar not verified",
            "Corporate actions and provider adjustment policy not verified",
            "No interpolation; incomplete sessions remain incomplete",
            "Previously inspected dataset: not a new independent holdout",
        ],
    )


def evaluate(rows, probabilities):
    result = metrics(rows, probabilities)
    decisions = [
        max(range(3), key=lambda k: p[k]) if max(p) >= 0.65 else None for p in probabilities
    ]
    covered = [(r, k) for r, k in zip(rows, decisions, strict=True) if k is not None]
    directional = [(r, k) for r, k in covered if k in (0, 2)]
    result.update(
        covered_predictions=len(covered),
        directional_predictions=len(directional),
        covered_accuracy=(sum(r["y"] == k for r, k in covered) / len(covered) if covered else None),
        directional_accuracy=(
            sum(r["y"] == k for r, k in directional) / len(directional) if directional else None
        ),
    )
    return result


def research_gate(evaluated, baseline):
    checks = dict(
        macro_f1_improves=evaluated["macro_f1"] > baseline["macro_f1"],
        brier_not_worse=evaluated["brier"] <= baseline["brier"],
        up_supported_and_recalled=(
            evaluated["classes"]["up"]["support"] > 0 and evaluated["classes"]["up"]["recall"] > 0
        ),
        down_supported_and_recalled=(
            evaluated["classes"]["down"]["support"] > 0
            and evaluated["classes"]["down"]["recall"] > 0
        ),
        directional_predictions_available=evaluated["directional_predictions"] > 0,
    )
    return dict(
        passed=all(checks.values()),
        checks=checks,
        failed_checks=[name for name, passed in checks.items() if not passed],
    )


def environment():
    packages = {}
    for package in ("numpy", "scipy", "scikit-learn", "catboost", "threadpoolctl"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return dict(
        python=platform.python_version(),
        platform=platform.platform(),
        packages=packages,
        implementation_sha256={
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("pipeline.py", "candidates.py", "experiment.py")
        },
    )


def compare(bars, *, model_names=DEFAULT_MODELS, data_kind="unknown"):
    if not model_names or len(set(model_names)) != len(model_names):
        raise ValueError("Specify unique model candidates")
    if set(model_names) - set(DEFAULT_MODELS):
        raise ValueError("Unknown model candidate")
    if data_kind not in ("historical", "synthetic", "unknown"):
        raise ValueError("Invalid data kind")
    quality = quality_report(bars)
    rows = samples(bars)
    if len(rows) < 240:
        raise ValueError("Need at least 240 labeled samples")
    a, b = int(len(rows) * 0.6), int(len(rows) * 0.8)
    training = [r for r in rows[:a] if r["target_at"] < rows[a]["as_of"]]
    validation = [r for r in rows[a:b] if r["target_at"] < rows[b]["as_of"]]
    testing = rows[b:]
    if min(map(len, (training, validation, testing))) < 30:
        raise ValueError("Need at least 30 samples per purged split")
    if {r["y"] for r in training} != {0, 1, 2}:
        raise ValueError("Training needs all three classes")
    candidates = []
    for name in model_names:
        model = fit_candidate(name, training)
        raw = model.probabilities(validation)
        temperature = min(
            TEMPERATURES, key=lambda t: metrics(validation, temperature_scale(raw, t))["log_loss"]
        )
        candidates.append(
            dict(
                name=name,
                model=model,
                temperature=temperature,
                parameters=model.parameters,
                validation=evaluate(validation, temperature_scale(raw, temperature)),
            )
        )
    # Selection locked before ANY candidate makes final-test predictions.
    # Failed selected model is never replaced by another model using test results.
    selected = max(
        candidates, key=lambda c: (c["validation"]["macro_f1"], -c["validation"]["brier"])
    )
    prior = [sum(r["y"] == k for r in training) / len(training) for k in range(3)]
    baseline = evaluate(testing, [prior for _ in testing])
    reports = []
    for candidate in candidates:
        evaluated = evaluate(
            testing,
            temperature_scale(candidate["model"].probabilities(testing), candidate["temperature"]),
        )
        reports.append(
            dict(
                name=candidate["name"],
                parameters=candidate["parameters"],
                temperature=candidate["temperature"],
                validation=candidate["validation"],
                test=evaluated,
                research_gate=research_gate(evaluated, baseline),
            )
        )
    selected_report = next(r for r in reports if r["name"] == selected["name"])
    passed = selected_report["research_gate"]["passed"]
    connection_candidate = selected["name"] if passed and data_kind == "historical" else None
    return dict(
        schema=2,
        quality=quality,
        features=FEATURES,
        labels=LABELS,
        horizon_minutes=60,
        threshold_percent=0.5,
        data_kind=data_kind,
        environment=environment(),
        selection_policy="validation macro-F1 then Brier; stable candidate order breaks ties",
        split=dict(
            train_samples=len(training),
            validation_samples=len(validation),
            test_samples=len(testing),
            training_target_end=training[-1]["target_at"].isoformat(),
            validation_start=validation[0]["as_of"].isoformat(),
            validation_target_end=validation[-1]["target_at"].isoformat(),
            test_start=testing[0]["as_of"].isoformat(),
            class_counts={
                name: dict(Counter(LABELS[r["y"]] for r in split_rows))
                for name, split_rows in (
                    ("training", training),
                    ("validation", validation),
                    ("test", testing),
                )
            },
        ),
        candidates=reports,
        selected=selected["name"],
        test=selected_report["test"],
        baseline=baseline,
        research_gate_passed=passed,
        gate_policy=(
            "strict F1 improvement, Brier no worse, up/down support and recall > 0, "
            "at least one up/down prediction at the fixed 65% threshold"
        ),
        gate_version="comparison-v2-directional-coverage",
        direction_threshold=0.65,
        app_connection_candidate=connection_candidate,
        app_connection_status=(
            "candidate_requires_independent_evaluation_and_runtime_adapter"
            if connection_candidate
            else "no_eligible_selected_model"
        ),
        deployment_approved=False,
        note=(
            "Exploratory comparison on previously inspected data. Test results cannot select "
            "a replacement candidate. No runtime model file is written or activated."
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--data-kind", choices=["historical", "synthetic"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", nargs="+", choices=DEFAULT_MODELS, default=DEFAULT_MODELS)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a NEW output file; reports must not be overwritten")
    if args.data_kind == "historical" and args.source.lower() in ("demo", "synthetic"):
        parser.error("Synthetic source cannot be declared historical")
    raw = args.csv.read_bytes()
    report = compare(read_csv(args.csv), model_names=args.models, data_kind=args.data_kind)
    report.update(
        source=args.source,
        data_kind=args.data_kind,
        csv_sha256=hashlib.sha256(raw).hexdigest(),
        created_at=datetime.now(UTC).isoformat(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    with args.output.open("x", encoding="utf-8") as f:
        f.write(content)
    print(
        json.dumps(
            dict(
                output=str(args.output),
                selected=report["selected"],
                research_gate_passed=report["research_gate_passed"],
                app_connection_candidate=report["app_connection_candidate"],
            )
        )
    )


if __name__ == "__main__":
    main()
