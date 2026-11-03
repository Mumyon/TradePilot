import json
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from test_risk import check, quotes, send

from app.ml.pipeline import KST, Bar, feature_rows, label, read_csv, samples, train
from app.models import PredictionRecord
from app.services import predictions
from app.services.candles import ingest


def generated_bars(days=24, start=datetime(2026, 8, 3, 9, tzinfo=KST)):
    # Test fixture only, never exported as a historical/production model.
    rows = []
    day = start
    while len(rows) < days * 78:
        if day.weekday() < 5:
            for i in range(78):
                price = 100000 + int(1100 * math.sin(i / 9 + day.day) + 400 * math.sin(i / 4))
                rows.append(
                    Bar(
                        (day + timedelta(minutes=5 * i)).astimezone(UTC),
                        price,
                        price + 50,
                        price - 50,
                        price,
                        1000 + i * 10,
                    )
                )
        day += timedelta(days=1)
    return rows


@pytest.fixture(scope="module")
def trained():
    bars = generated_bars()
    return bars, train(bars, "005930", "fixture", "synthetic", "test-fixture")


def test_training_chronology_calibration_and_metadata(trained):
    bars, artifact = trained
    e = artifact["evaluation"]
    assert datetime.fromisoformat(e["training_target_end"]) < datetime.fromisoformat(
        e["validation_start"]
    )
    assert datetime.fromisoformat(e["validation_target_end"]) < datetime.fromisoformat(
        e["test_start"]
    )
    assert len(e["walk_forward"]) == 3
    assert e["test"]["samples"] >= 30 and e["baseline"]["samples"] == e["test"]["samples"]
    assert set(e["test"]["classes"]) == {"up", "neutral", "down"}
    assert 0 <= e["test"]["expected_calibration_error"] <= 1
    assert artifact["data_kind"] == "synthetic"
    assert label(10000, 10050) == 1 and label(10000, 9950) == 1
    assert label(10000, 10051) == 0 and label(10000, 9949) == 2
    # Future changes cannot influence features before that timestamp.
    prefix = bars[:70]
    changed = bars[:70] + [replace(b, close=b.close * 2, high=b.high * 2) for b in bars[70:]]
    assert feature_rows(prefix) == [
        r for r in feature_rows(changed) if r["as_of"] <= prefix[-1].as_of
    ]
    assert all(r["target_at"] - r["as_of"] == timedelta(hours=1) for r in samples(bars))


def test_csv_rejects_naive_and_duplicate_timestamps(tmp_path):
    file = tmp_path / "bars.csv"
    header = "opened_at,open_won,high_won,low_won,close_won,volume\n"
    file.write_text(header + "2026-08-03T09:00:00,100,110,90,105,10\n")
    with pytest.raises(ValueError):
        read_csv(file)
    row = "2026-08-03T09:00:00+09:00,100,110,90,105,10\n"
    file.write_text(header + row + row)
    with pytest.raises(ValueError):
        read_csv(file)
    file.write_text(header + row)
    assert len(read_csv(file)) == 1
    with pytest.raises(ValueError):
        train(read_csv(file), "005930", "csv", "historical", "hash")


def test_missing_and_synthetic_model_not_served(service, tmp_path, trained):
    _, sessions, _, settings = service
    _, artifact = trained
    path = tmp_path / "model.json"
    path.write_text(json.dumps(artifact))
    with sessions.begin() as db:
        assert (
            predictions.get_prediction(db, "005930", settings)["reason"] == "model_not_configured"
        )
        settings.prediction_model_path = str(path)
        assert predictions.get_prediction(db, "005930", settings)["reason"] == "synthetic_model"
        path.write_text("{}")
        assert predictions.get_prediction(db, "005930", settings)["reason"] == "model_invalid"


def test_prediction_persistence_outcome_and_staleness(service, trained, monkeypatch):
    _, sessions, _, _ = service
    _, artifact = trained
    bars = generated_bars(days=1, start=datetime(2026, 10, 16, 9, tzinfo=KST))
    as_of = bars[45].as_of
    monkeypatch.setattr(predictions, "now", lambda: as_of + timedelta(seconds=10))
    with sessions.begin() as db:
        ingest(
            db,
            "005930",
            "5m",
            [
                dict(
                    opened_at=b.opened_at,
                    open_won=b.open,
                    high_won=b.high,
                    low_won=b.low,
                    close_won=b.close,
                    volume=b.volume,
                    complete=True,
                    source="fixture",
                )
                for b in bars[:46]
            ],
        )
        result = predictions.infer(db, "005930", artifact)
        assert result["status"] == "available"
        assert abs(sum(result[k] for k in ["up", "neutral", "down"]) - 1) < 1e-9
        assert predictions.infer(db, "005930", artifact)["prediction_id"] == result["prediction_id"]
    with sessions.begin() as db:
        b = bars[57]
        ingest(
            db,
            "005930",
            "5m",
            [
                dict(
                    opened_at=b.opened_at,
                    open_won=b.open,
                    high_won=b.high,
                    low_won=b.low,
                    close_won=b.close,
                    volume=b.volume,
                    complete=True,
                    source="fixture",
                )
            ],
        )
        monkeypatch.setattr(predictions, "now", lambda: as_of + timedelta(hours=1, seconds=1))
        predictions.resolve_outcomes(db)
        record = db.get(PredictionRecord, result["prediction_id"])
        assert record.outcome["status"] == "resolved"
        assert record.data == result
        assert predictions.infer(db, "005930", artifact)["status"] == "unavailable"


def test_journal_preserves_warnings_and_declines(service):
    client = quotes(service)
    body, result = check(client)
    assert (
        client.post(f"/v1/orders/check/{result['check_id']}/dismiss").json()["decision"]
        == "dismissed"
    )
    # An explicitly declined check cannot later be used to submit an order.
    assert (
        send(client, body, result, warning_acknowledged=True, trade_reason="확인 완료").json()[
            "status"
        ]
        == "rejected"
    )
    report = client.get("/v1/journal").json()
    assert report["summary"]["warning_counts"]["fomo"] == 1
    assert report["summary"]["warning_decisions"]["dismissed"] == 1
    assert report["summary"]["filled_orders"] == 0
    assert report["summary"]["plan_compliance"] is None
    assert report["items"][0]["prediction"]["status"] == "unavailable"
    assert report["summary"]["prediction_accuracy"] is None


def test_journal_fill_plan_and_account_isolation(service):
    from test_portfolio import settle
    from test_risk import plan

    from app.cli import create_user

    client = quotes(service, current=100000)
    p = plan(service)
    body, result = check(client, plan_id=p)
    receipt = send(client, body, result, trade_reason="사전 계획 조건 충족").json()
    settle(service, 100000)
    report = client.get("/v1/journal").json()
    assert report["summary"]["filled_orders"] == 1
    assert report["summary"]["plan_compliance"] == 1
    assert report["items"][0]["trade_reason"] == "사전 계획 조건 충족"
    assert report["items"][0]["fill"]["price_won"] == "100000"
    _, sessions, uid, _ = service
    with sessions.begin() as db:
        user = create_user(db, "journal@example.test", "another-password-123")
    token = client.post(
        "/v1/auth/login", json=dict(email=user.email, password="another-password-123")
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    assert client.get("/v1/journal").json()["items"] == []
    assert client.get(f"/v1/orders/{receipt['order_id']}/analysis").status_code == 404
