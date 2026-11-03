"""5-minute OHLCV -> one-hour 3-class baseline model, using only stdlib.

Input timestamps are bar OPEN times. Labels never cross gaps or market sessions.
JSON artifacts are data, never executable pickle files.
"""

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
FEATURES = [
    "return_1",
    "return_3",
    "ma5_gap",
    "ma20_gap",
    "rsi14",
    "macd",
    "volume_change",
    "volume_ratio",
]
LABELS = ["up", "neutral", "down"]
HORIZON = timedelta(hours=1)
BAR = timedelta(minutes=5)


@dataclass(frozen=True)
class Bar:
    opened_at: datetime
    open: int
    high: int
    low: int
    close: int
    volume: int

    @property
    def as_of(self):
        return self.opened_at + BAR


def validate_bars(bars):
    previous = None
    for b in bars:
        local = b.opened_at.astimezone(KST)
        if (
            b.opened_at.tzinfo is None
            or local.second
            or local.microsecond
            or local.minute % 5
            or local.weekday() > 4
            or not (9 * 60 <= local.hour * 60 + local.minute <= 15 * 60 + 25)
            or min(b.open, b.high, b.low, b.close) <= 0
            or b.volume < 0
            or b.high < max(b.open, b.close)
            or b.low > min(b.open, b.close)
            or b.high < b.low
            or (previous is not None and b.opened_at <= previous)
        ):
            raise ValueError("Invalid OHLCV, timestamp/order or KRX regular-session time")
        previous = b.opened_at


def read_csv(path):
    bars = []
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"opened_at", "open_won", "high_won", "low_won", "close_won", "volume"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("CSV requires: " + ", ".join(sorted(required)))
        for row in reader:
            stamp = datetime.fromisoformat(row["opened_at"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("CSV timestamps must include a timezone (e.g. +09:00)")
            bars.append(
                Bar(
                    stamp.astimezone(UTC),
                    *[
                        int(row[k])
                        for k in ["open_won", "high_won", "low_won", "close_won", "volume"]
                    ],
                )
            )
    validate_bars(bars)
    return bars


def feature_rows(bars):
    """Reset indicators on missing bars/day boundaries. No forward fill."""
    rows = []
    segment = []
    ema12 = ema26 = 0.0
    previous = None
    for b in bars:
        if previous is None or b.opened_at - previous != BAR:
            segment = []
            ema12 = ema26 = float(b.close)
        else:
            ema12 += (b.close - ema12) * 2 / 13
            ema26 += (b.close - ema26) * 2 / 27
        segment.append(b)
        previous = b.opened_at
        if len(segment) < 35:
            continue
        closes = [r.close for r in segment[-20:]]
        deltas = [
            segment[i].close - segment[i - 1].close for i in range(len(segment) - 14, len(segment))
        ]
        gain = sum(max(0, d) for d in deltas) / 14
        loss = sum(max(0, -d) for d in deltas) / 14
        rsi = 50.0 if gain + loss == 0 else 100 * gain / (gain + loss)
        vol_mean = mean(r.volume for r in segment[-20:])
        x = [
            b.close / segment[-2].close - 1,
            b.close / segment[-4].close - 1,
            b.close / mean(closes[-5:]) - 1,
            b.close / mean(closes) - 1,
            rsi / 100,
            (ema12 - ema26) / b.close,
            b.volume / max(1, segment[-2].volume) - 1,
            b.volume / max(1, vol_mean),
        ]
        rows.append(
            dict(
                as_of=b.as_of,
                price=b.close,
                x=x,
                indicators=dict(
                    ma5=mean(closes[-5:]),
                    ma20=mean(closes),
                    rsi14=rsi,
                    macd=ema12 - ema26,
                    volume=b.volume,
                ),
            )
        )
    return rows


def label(base, future):
    # Exact integer threshold: +/- 0.5% (the boundary belongs to neutral).
    difference = (future - base) * 200
    return 0 if difference > base else 2 if difference < -base else 1


def samples(bars):
    by_time = {b.as_of: b for b in bars}
    result = []
    for row in feature_rows(bars):
        stamp = row["as_of"]
        future = by_time.get(stamp + HORIZON)
        if future is None or stamp.astimezone(KST).date() != future.as_of.astimezone(KST).date():
            continue
        if any(stamp + BAR * i not in by_time for i in range(1, 13)):
            continue
        result.append({**row, "target_at": future.as_of, "y": label(row["price"], future.close)})
    return result


def probabilities(weights, x, temperature=1.0):
    logits = [sum(a * b for a, b in zip(w, [1.0] + x, strict=True)) / temperature for w in weights]
    top = max(logits)
    exp = [math.exp(v - top) for v in logits]
    total = sum(exp)
    return [v / total for v in exp]


def scale(x, center, spread):
    return [max(-10.0, min(10.0, (v - c) / s)) for v, c, s in zip(x, center, spread, strict=True)]


def fit(rows, epochs=100, *, balanced=False):
    center = [mean(r["x"][j] for r in rows) for j in range(len(FEATURES))]
    spread = [
        max(1e-8, math.sqrt(mean((r["x"][j] - center[j]) ** 2 for r in rows)))
        for j in range(len(FEATURES))
    ]
    data = [(scale(r["x"], center, spread), r["y"]) for r in rows]
    counts = [sum(y == k for _, y in data) for k in range(3)]
    class_weights = [len(data) / (3 * max(1, n)) if balanced else 1.0 for n in counts]
    weights = [[0.0] * (len(FEATURES) + 1) for _ in LABELS]
    # Full-batch softmax regression with L2 regularization; deterministic training.
    for _ in range(epochs):
        gradient = [[0.0] * (len(FEATURES) + 1) for _ in LABELS]
        for x, y in data:
            p = probabilities(weights, x)
            for k in range(3):
                error = (p[k] - (1 if k == y else 0)) * class_weights[y]
                for j, v in enumerate([1.0] + x):
                    gradient[k][j] += error * v
        for k in range(3):
            for j in range(len(FEATURES) + 1):
                weights[k][j] -= 0.15 * (
                    gradient[k][j] / len(data) + (0.001 * weights[k][j] if j else 0)
                )
    return dict(center=center, spread=spread, weights=weights, temperature=1.0)


def predict(model, row):
    return probabilities(
        model["weights"], scale(row["x"], model["center"], model["spread"]), model["temperature"]
    )


def metrics(rows, probs):
    matrix = [[0] * 3 for _ in LABELS]
    brier = nll = 0.0
    bins = [[] for _ in range(10)]
    for row, p in zip(rows, probs, strict=True):
        y = row["y"]
        chosen = max(range(3), key=lambda k: p[k])
        matrix[y][chosen] += 1
        brier += sum((v - (1 if k == y else 0)) ** 2 for k, v in enumerate(p))
        nll -= math.log(max(1e-12, p[y]))
        bins[min(9, int(max(p) * 10))].append((max(p), chosen == y))
    classes = {}
    for k, name in enumerate(LABELS):
        precision = matrix[k][k] / max(1, sum(r[k] for r in matrix))
        recall = matrix[k][k] / max(1, sum(matrix[k]))
        classes[name] = dict(
            precision=precision,
            recall=recall,
            f1=2 * precision * recall / max(1e-12, precision + recall),
            support=sum(matrix[k]),
        )
    reliability = [
        dict(count=len(b), confidence=mean(v[0] for v in b), accuracy=mean(v[1] for v in b))
        for b in bins
        if b
    ]
    n = len(rows)
    return dict(
        samples=n,
        start=rows[0]["as_of"].isoformat(),
        end=rows[-1]["target_at"].isoformat(),
        accuracy=sum(matrix[i][i] for i in range(3)) / n,
        macro_f1=mean(c["f1"] for c in classes.values()),
        classes=classes,
        confusion_matrix=matrix,
        brier=brier / n,
        log_loss=nll / n,
        reliability=reliability,
        expected_calibration_error=sum(
            b["count"] * abs(b["confidence"] - b["accuracy"]) for b in reliability
        )
        / n,
        abstention_rate=sum(max(p) < 0.65 for p in probs) / n,
    )


def train(bars, symbol, source, data_kind, csv_hash):
    validate_bars(bars)
    rows = samples(bars)
    if len(rows) < 240:
        raise ValueError(
            "At least 240 labeled samples are required; supply more complete trading days"
        )
    a, b = int(len(rows) * 0.6), int(len(rows) * 0.8)
    training = [r for r in rows[:a] if r["target_at"] < rows[a]["as_of"]]
    validation = [r for r in rows[a:b] if r["target_at"] < rows[b]["as_of"]]
    testing = rows[b:]
    if min(len(training), len(validation), len(testing)) < 30 or {r["y"] for r in training} != {
        0,
        1,
        2,
    }:
        raise ValueError("Need at least 30 samples per split and all three classes in training")
    model = fit(training)
    # Temperature is chosen on validation only; final test is never used for fitting.
    temperatures = [0.5, 0.75, 1, 1.5, 2, 3]
    model["temperature"] = min(
        temperatures,
        key=lambda t: metrics(
            validation, [predict({**model, "temperature": t}, r) for r in validation]
        )["log_loss"],
    )
    prior = [sum(r["y"] == k for r in training) / len(training) for k in range(3)]
    evaluated = metrics(testing, [predict(model, r) for r in testing])
    baseline = metrics(testing, [prior for _ in testing])
    folds = []
    for fraction in [0.4, 0.6, 0.8]:
        boundary = int(len(rows) * fraction)
        end = min(len(rows), boundary + int(len(rows) * 0.2))
        train_rows = [r for r in rows[:boundary] if r["target_at"] < rows[boundary]["as_of"]]
        test_rows = rows[boundary:end]
        fold = fit(train_rows, epochs=60)
        folds.append(metrics(test_rows, [predict(fold, r) for r in test_rows]))
    artifact = dict(
        schema_version=1,
        features=FEATURES,
        labels=LABELS,
        model=model,
        symbol=symbol,
        source=source,
        data_kind=data_kind,
        csv_sha256=csv_hash,
        data_start=bars[0].opened_at.isoformat(),
        data_end=bars[-1].as_of.isoformat(),
        created_at=datetime.now(UTC).isoformat(),
        horizon_minutes=60,
        threshold_percent=0.5,
        direction_threshold=0.65,
        evaluation=dict(
            test=evaluated,
            baseline=baseline,
            walk_forward=folds,
            train_samples=len(training),
            validation_samples=len(validation),
            split_policy="chronological 60/20/20; purge overlapping future labels",
            training_target_end=training[-1]["target_at"].isoformat(),
            validation_start=validation[0]["as_of"].isoformat(),
            validation_target_end=validation[-1]["target_at"].isoformat(),
            test_start=testing[0]["as_of"].isoformat(),
        ),
    )
    artifact["quality_gate_passed"] = (
        evaluated["macro_f1"] >= baseline["macro_f1"] and evaluated["brier"] <= baseline["brier"]
    )
    artifact["version"] = (
        "softmax-" + hashlib.sha256(json.dumps(artifact, sort_keys=True).encode()).hexdigest()[:16]
    )
    return artifact


def load_artifact(path):
    artifact = json.loads(Path(path).read_text())
    if (
        artifact["schema_version"] != 1
        or artifact["features"] != FEATURES
        or artifact["labels"] != LABELS
    ):
        raise ValueError("Unsupported model schema")
    model = artifact["model"]
    vectors = [model["center"], model["spread"], *model["weights"]]
    if (
        [len(v) for v in vectors] != [8, 8, 9, 9, 9]
        or any(not math.isfinite(v) for vec in vectors for v in vec)
        or any(v <= 0 for v in model["spread"])
        or model["temperature"] not in [0.5, 0.75, 1, 1.5, 2, 3]
    ):
        raise ValueError("Invalid model parameters")
    return artifact
