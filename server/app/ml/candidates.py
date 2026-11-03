"""Fixed CPU model candidates for offline comparison, imported on demand.

Probability columns always follow pipeline.LABELS (up, neutral, down).
No persistence, external network access, or live inference activation.
"""

import math
from dataclasses import dataclass

from .pipeline import fit, predict

BASELINE_MODELS = ("softmax", "balanced-softmax")
DEFAULT_MODELS = (*BASELINE_MODELS, "hist-gradient-boosting", "catboost")
TEMPERATURES = (0.5, 0.75, 1, 1.5, 2, 3)


def ordered_probabilities(values, classes):
    classes = [int(k) for k in classes]
    if sorted(classes) != [0, 1, 2]:
        raise ValueError("Candidate must provide exactly three classes: 0, 1, 2")
    result = []
    for values_row in values:
        if len(values_row) != 3:
            raise ValueError("Invalid probability shape")
        row = [float(values_row[classes.index(k)]) for k in range(3)]
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in row):
            raise ValueError("Invalid candidate probabilities")
        if not math.isclose(sum(row), 1, abs_tol=1e-8):
            raise ValueError("Candidate probabilities must sum to one")
        result.append(row)
    return result


def temperature_scale(probabilities, temperature):
    if temperature not in TEMPERATURES:
        raise ValueError("Unsupported temperature")
    if temperature == 1:
        return [list(row) for row in probabilities]
    result = []
    for row in probabilities:
        logits = [math.log(max(1e-15, p)) / temperature for p in row]
        weights = [math.exp(v - max(logits)) for v in logits]
        result.append([v / sum(weights) for v in weights])
    return result


@dataclass
class Candidate:
    name: str
    model: object
    parameters: dict

    def probabilities(self, rows):
        if self.name in BASELINE_MODELS:
            values = [predict(self.model, r) for r in rows]
            return ordered_probabilities(values, [0, 1, 2])
        from threadpoolctl import threadpool_limits

        with threadpool_limits(limits=1):
            values = self.model.predict_proba([r["x"] for r in rows])
        return ordered_probabilities(values, self.model.classes_)


def fit_candidate(name, training):
    if name not in DEFAULT_MODELS:
        raise ValueError(f"Unknown model candidate: {name}")
    if name in BASELINE_MODELS:
        balanced = name == "balanced-softmax"
        return Candidate(
            name, fit(training, balanced=balanced), dict(balanced=balanced, epochs=100)
        )
    try:
        from threadpoolctl import threadpool_limits

        if name == "hist-gradient-boosting":
            from sklearn.ensemble import HistGradientBoostingClassifier

            parameters = dict(
                loss="log_loss",
                learning_rate=0.05,
                max_iter=120,
                max_depth=3,
                max_leaf_nodes=7,
                min_samples_leaf=20,
                l2_regularization=1.0,
                early_stopping=False,
                random_state=42,
            )
            model = HistGradientBoostingClassifier(**parameters)
        else:
            from catboost import CatBoostClassifier

            parameters = dict(
                loss_function="MultiClass",
                classes_count=3,
                iterations=120,
                depth=3,
                learning_rate=0.05,
                l2_leaf_reg=3.0,
                has_time=True,
                boosting_type="Plain",
                bootstrap_type="No",
                random_strength=0,
                random_seed=42,
                thread_count=1,
                allow_writing_files=False,
                verbose=False,
            )
            model = CatBoostClassifier(**parameters)
    except ImportError as exc:
        raise ValueError(
            "Tree candidates require: uv sync --frozen --extra model-comparison"
        ) from exc
    # No random internal validation split, early stopping, or test eval_set.
    with threadpool_limits(limits=1):
        model.fit([r["x"] for r in training], [r["y"] for r in training])
    return Candidate(name, model, parameters)
