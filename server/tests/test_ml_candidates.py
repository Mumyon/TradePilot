import builtins
import math

import pytest
from test_predictions_journal import generated_bars

from app.ml.candidates import fit_candidate, ordered_probabilities, temperature_scale
from app.ml.pipeline import samples


def test_probability_columns_are_explicitly_reordered():
    assert ordered_probabilities([[0.6, 0.1, 0.3]], [2, 0, 1]) == [[0.1, 0.3, 0.6]]


@pytest.mark.parametrize(
    "values,classes",
    [
        ([[0.2, 0.8]], [0, 1]),
        ([[0.2, 0.4, 0.4]], [0, 0, 2]),
        ([[0.2, 0.2, 0.2]], [0, 1, 2]),
        ([[float("nan"), 0.5, 0.5]], [0, 1, 2]),
        ([[1.2, -0.1, -0.1]], [0, 1, 2]),
    ],
)
def test_invalid_model_probabilities_fail_closed(values, classes):
    with pytest.raises(ValueError):
        ordered_probabilities(values, classes)


def test_temperature_scaling_preserves_class_order_and_normalizes():
    for temperature in [0.5, 0.75, 1, 1.5, 2, 3]:
        probabilities = temperature_scale([[0.7, 0.2, 0.1], [1, 0, 0]], temperature)
        for p in probabilities:
            assert all(math.isfinite(v) and 0 <= v <= 1 for v in p)
            assert sum(p) == pytest.approx(1)
            assert p.index(max(p)) == 0
    assert temperature_scale([[0.7, 0.2, 0.1]], 1) == [[0.7, 0.2, 0.1]]
    with pytest.raises(ValueError):
        temperature_scale([[0.7, 0.2, 0.1]], 0)


@pytest.mark.parametrize("name", ["hist-gradient-boosting", "catboost"])
def test_tree_fits_are_deterministic_and_no_random_validation(name, tmp_path, monkeypatch):
    pytest.importorskip("sklearn")
    pytest.importorskip("catboost")
    rows = samples(generated_bars(days=8))
    monkeypatch.chdir(tmp_path)
    first = fit_candidate(name, rows[:160])
    second = fit_candidate(name, rows[:160])
    assert first.probabilities(rows[160:170]) == second.probabilities(rows[160:170])
    assert first.model.classes_.tolist() == [0, 1, 2]
    if name == "hist-gradient-boosting":
        assert first.parameters["early_stopping"] is False
    else:
        assert first.parameters["has_time"] is True
        assert first.parameters["thread_count"] == 1
        assert first.parameters["allow_writing_files"] is False
    assert not list(tmp_path.iterdir())


def test_missing_extra_has_actionable_error_and_does_not_change_baseline(monkeypatch):
    original = builtins.__import__

    def without_trees(name, *args, **kwargs):
        if name.split(".")[0] in ("sklearn", "catboost", "threadpoolctl"):
            raise ImportError("optional dependency absent")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_trees)
    with pytest.raises(ValueError, match="extra model-comparison"):
        fit_candidate("hist-gradient-boosting", [])
    baseline = fit_candidate("softmax", samples(generated_bars(days=8))[:40])
    assert baseline.name == "softmax"
