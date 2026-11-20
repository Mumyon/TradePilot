from copy import deepcopy
from datetime import datetime, timedelta

import numpy as np
import pytest

from app.ml.pipeline import KST
from tool import walk_forward_toss_models as experiment


@pytest.mark.parametrize("period", ["calibration", "selection", "test"])
def test_missing_class_does_not_remove_evaluation_window(monkeypatch, period):
    rows = []
    for day in range(52):
        for sample in range(12):
            stamp = datetime(2025, 1, 1, 10, tzinfo=KST) + timedelta(days=day, minutes=5 * sample)
            rows.append(dict(as_of=stamp, target_at=stamp + timedelta(hours=1), y=sample % 3))
    features = np.zeros((len(rows), 2))

    def fixed_candidates(_x, _rocket, _returns, _volatility, _labels, _train, future):
        return {"fixed": np.tile([0.7, 0.2, 0.1], (len(future), 1))}

    monkeypatch.setattr(experiment, "candidate_probabilities", fixed_candidates)

    def run(batch):
        return experiment.walk_forward(
            (batch, features, features, np.zeros(len(rows)), np.ones(len(rows)))
        )

    original = run(rows)
    changed = deepcopy(rows)
    start, end = {"calibration": (26, 34), "selection": (34, 42), "test": (42, 52)}[period]
    for row in changed[start * 12 : end * 12]:
        row["y"] = 1
    result = run(changed)
    assert len(original["folds"]) == len(result["folds"]) == 1
    assert result["baseline"]["samples"] == original["baseline"]["samples"] == 120
    if period == "test":
        assert result["folds"][0]["nominee"] == original["folds"][0]["nominee"]
        assert result["models"]["fixed"]["test"] != original["models"]["fixed"]["test"]


def test_test_start_skips_earlier_windows_and_anchors_first_window(monkeypatch):
    start = datetime(2025, 1, 1, 10, tzinfo=KST)
    rows = [
        dict(as_of=stamp, target_at=stamp + timedelta(hours=1), y=sample % 3)
        for day in range(65)
        for sample in range(12)
        for stamp in [start + timedelta(days=day, minutes=5 * sample)]
    ]
    features = np.zeros((len(rows), 2))
    monkeypatch.setattr(
        experiment,
        "candidate_probabilities",
        lambda *args: {"fixed": np.tile([0.7, 0.2, 0.1], (len(args[-1]), 1))},
    )
    cutoff = (start + timedelta(days=48)).date()
    result = experiment.walk_forward(
        (rows, features, features, np.zeros(len(rows)), np.ones(len(rows))), test_start=cutoff
    )
    assert len(result["folds"]) == 1
    assert result["folds"][0]["start"] == str(cutoff)
    assert result["baseline"]["samples"] == 120
