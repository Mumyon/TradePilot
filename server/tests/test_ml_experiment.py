from copy import deepcopy
from dataclasses import replace
from datetime import datetime

import pytest
from test_predictions_journal import generated_bars

from app.ml import experiment
from app.ml.candidates import BASELINE_MODELS, DEFAULT_MODELS
from app.ml.pipeline import KST, fit, predict, samples


def test_quality_reports_observed_session_gaps_without_filling():
    bars = generated_bars(days=8)
    missing = bars[40]
    report = experiment.quality_report(bars[:40] + bars[41:])
    assert report["bars"] == len(bars) - 1
    assert (
        missing.opened_at.astimezone(KST).strftime("%H:%M")
        in report["sessions"][0]["missing_open_times"]
    )
    assert report["labeled_samples"] < len(samples(bars))


def test_quality_rejects_unfinished_data():
    bars = generated_bars(days=1)
    with pytest.raises(ValueError, match="Future"):
        experiment.quality_report([replace(bars[0], opened_at=datetime(2099, 1, 5, 9, tzinfo=KST))])


@pytest.mark.parametrize("model_names", [BASELINE_MODELS, DEFAULT_MODELS])
def test_holdout_labels_cannot_change_selection(monkeypatch, model_names):
    if model_names == DEFAULT_MODELS:
        pytest.importorskip("sklearn")
        pytest.importorskip("catboost")
    bars = generated_bars(days=12)
    original = experiment.compare(bars, model_names=model_names)
    rows = deepcopy(samples(bars))
    for row in rows[int(len(rows) * 0.8) :]:
        row["y"] = (row["y"] + 1) % 3
    monkeypatch.setattr(experiment, "samples", lambda _: rows)
    changed = experiment.compare(bars, model_names=model_names)
    assert original["selected"] == changed["selected"]
    for before, after in zip(original["candidates"], changed["candidates"], strict=True):
        assert {k: before[k] for k in ("name", "parameters", "temperature", "validation")} == {
            k: after[k] for k in ("name", "parameters", "temperature", "validation")
        }
    assert original["test"] != changed["test"]
    s = original["split"]
    assert s["training_target_end"] < s["validation_start"]
    assert s["validation_target_end"] < s["test_start"]
    assert original["deployment_approved"] is False


def test_default_fit_preserved_and_balanced_probabilities_valid():
    rows = samples(generated_bars(days=8))
    normal = fit(rows, epochs=3)
    assert normal == fit(rows, epochs=3, balanced=False)
    balanced = fit(rows, epochs=3, balanced=True)
    assert normal != balanced
    probabilities = predict(balanced, rows[0])
    assert sum(probabilities) == pytest.approx(1)
    assert all(0 <= p <= 1 for p in probabilities)


def test_failed_selection_is_not_replaced_using_test_results(monkeypatch):
    from types import SimpleNamespace

    bars = generated_bars(days=12)
    rows = samples(bars)
    test_start = rows[int(len(rows) * 0.8)]["as_of"]

    def fake_fit(name, training):
        def probabilities(batch):
            result = []
            for row in batch:
                correct = (name == "softmax") == (row["as_of"] < test_start)
                chosen = row["y"] if correct else (row["y"] + 1) % 3
                result.append([0.98 if k == chosen else 0.01 for k in range(3)])
            return result

        return SimpleNamespace(parameters={}, probabilities=probabilities)

    monkeypatch.setattr(experiment, "fit_candidate", fake_fit)
    report = experiment.compare(bars, model_names=("softmax", "catboost"), data_kind="historical")
    assert report["selected"] == "softmax"
    assert report["research_gate_passed"] is False
    assert report["candidates"][1]["research_gate"]["passed"] is True
    assert report["app_connection_candidate"] is None


@pytest.mark.parametrize("kind", ["historical", "synthetic", "unknown"])
def test_only_passing_historical_selection_is_connection_candidate(monkeypatch, kind):
    from types import SimpleNamespace

    monkeypatch.setattr(
        experiment,
        "fit_candidate",
        lambda *_: SimpleNamespace(
            parameters={},
            probabilities=lambda rows: [
                [0.98 if k == r["y"] else 0.01 for k in range(3)] for r in rows
            ],
        ),
    )
    report = experiment.compare(generated_bars(days=12), model_names=("softmax",), data_kind=kind)
    assert report["research_gate_passed"] is True
    assert report["app_connection_candidate"] == ("softmax" if kind == "historical" else None)
    assert report["deployment_approved"] is False


def test_abstention_or_only_neutral_is_not_directional_gate_pass():
    rows = samples(generated_bars(days=8))
    baseline = experiment.evaluate(rows, [[0.01, 0.98, 0.01] for _ in rows])
    evaluated = experiment.evaluate(
        rows, [[0.4 if k == r["y"] else 0.3 for k in range(3)] for r in rows]
    )
    assert evaluated["accuracy"] == 1
    assert evaluated["directional_accuracy"] is None
    gate = experiment.research_gate(evaluated, baseline)
    assert gate["checks"]["macro_f1_improves"] is True
    assert gate["checks"]["up_supported_and_recalled"] is True
    assert gate["checks"]["down_supported_and_recalled"] is True
    assert "directional_predictions_available" in gate["failed_checks"]
    assert gate["passed"] is False
    neutral = experiment.evaluate(rows, [[0.01, 0.98, 0.01] for _ in rows])
    assert neutral["covered_predictions"] == len(rows)
    assert neutral["directional_predictions"] == 0


@pytest.mark.parametrize("model_names", [(), ("softmax", "softmax"), ("unknown",)])
def test_invalid_candidate_lists_rejected(model_names):
    with pytest.raises(ValueError):
        experiment.compare([], model_names=model_names)


def test_cli_refuses_to_overwrite_before_training(tmp_path, monkeypatch):
    output = tmp_path / "report.json"
    output.write_text("preserved")
    monkeypatch.setattr(
        "sys.argv",
        [
            "experiment",
            "--csv",
            "nonexistent.csv",
            "--source",
            "test",
            "--data-kind",
            "synthetic",
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit) as error:
        experiment.main()
    assert error.value.code == 2
    assert output.read_text() == "preserved"
