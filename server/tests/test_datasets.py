from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import Candle, Dataset


def csv_text(count=30):
    lines = ["opened_at,open_won,high_won,low_won,close_won,volume"]
    start = datetime(2026, 10, 16, tzinfo=UTC)
    for i in range(count):
        stamp = start + timedelta(minutes=5 * i)
        p = 70000 + i * 10
        lines.append(f"{stamp.isoformat()},{p},{p + 50},{p - 50},{p},1000")
    return "\n".join(lines)


def body(text=None):
    return dict(
        name="fixture",
        symbol="005930",
        provider="test generator",
        data_kind="synthetic",
        csv_text=csv_text() if text is None else text,
    )


def test_validate_store_replay_and_private_backtest(service):
    client, sessions, *_ = service
    data = body()
    preview = client.post("/v1/datasets/validate", json=data)
    assert preview.status_code == 200, preview.text
    assert preview.json()["longest_contiguous"] == 30
    with sessions() as db:
        assert db.scalar(select(func.count(Dataset.id))) == 0
    saved = client.post("/v1/datasets", json=data)
    assert saved.status_code == 201, saved.text
    did = saved.json()["id"]
    assert client.post("/v1/datasets", json=data).json()["id"] == did
    assert len(client.get("/v1/datasets").json()["items"]) == 1
    sid = client.post("/v1/strategies", json=dict(name="csv", symbol="005930")).json()["id"]
    run = client.post(
        f"/v1/strategies/{sid}/backtests",
        json=dict(
            source="demo", dataset_id=did, start="2026-10-16T00:00:00Z", end="2026-10-16T05:00:00Z"
        ),
    )
    assert run.status_code == 201, run.text
    assert run.json()["data_label"] == "합성 CSV 데이터"
    assert run.json()["bar_count"] == 30
    assert run.json()["dataset"]["sha256"] == saved.json()["sha256"]
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Candle)) == 0
    assert client.delete("/v1/datasets/" + did).status_code == 200
    assert client.get("/v1/backtests/" + run.json()["id"]).json()["dataset"]["id"] == did
    assert (
        client.post(
            f"/v1/strategies/{sid}/backtests",
            json=dict(
                source="demo",
                dataset_id=did,
                start="2026-10-16T00:00:00Z",
                end="2026-10-16T05:00:00Z",
            ),
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "text",
    [
        "wrong,header\n1,2",
        csv_text(1) + "\n" + csv_text(1).splitlines()[1],
        csv_text(1).replace("+00:00", ""),
        csv_text(1).replace("70050", "69900"),
        csv_text(1).replace("1000", "-1"),
        csv_text(1).replace("2026-10-16", "2099-10-16"),
        csv_text(1).replace("2026-10-16", "2026-10-17"),
        csv_text(1).replace("00:00:00", "00:01:00"),
        '"unfinished header',
        "opened_at,open_won,high_won,low_won,close_won,volume\n",
    ],
)
def test_invalid_csv_is_atomic(service, text):
    client, sessions, *_ = service
    response = client.post("/v1/datasets", json=body(text))
    assert response.status_code == 422, response.text
    with sessions() as db:
        assert db.scalar(select(func.count(Dataset.id))) == 0
        assert db.scalar(select(func.count()).select_from(Candle)) == 0


def test_dataset_ownership_and_symbol_mismatch(service):
    client, *_ = service
    did = client.post("/v1/datasets", json=body()).json()["id"]
    sid = client.post("/v1/strategies", json=dict(name="wrong", symbol="000660")).json()["id"]
    request = dict(
        source="private_csv",
        dataset_id=did,
        start="2026-10-16T00:00:00Z",
        end="2026-10-16T05:00:00Z",
    )
    assert client.post(f"/v1/strategies/{sid}/backtests", json=request).status_code == 422
    account = dict(
        email="csv-other@example.com",
        password="csv-test-password",
        password_confirmation="csv-test-password",
    )
    assert client.post("/v1/auth/signup", json=account).status_code == 201
    token = client.post("/v1/auth/login", json=account).json()["access_token"]
    client.headers["Authorization"] = "Bearer " + token
    assert client.get("/v1/datasets").json()["items"] == []
    assert client.delete("/v1/datasets/" + did).status_code == 404
    own = client.post("/v1/strategies", json=dict(name="other", symbol="005930")).json()["id"]
    assert client.post(f"/v1/strategies/{own}/backtests", json=request).status_code == 404


def test_gap_and_bom_preview(service):
    client, *_ = service
    lines = csv_text().splitlines()
    del lines[10]
    result = client.post("/v1/datasets/validate", json=body("\ufeff" + "\n".join(lines)))
    assert result.status_code == 200
    assert result.json()["gap_count"] == 1
    assert result.json()["bar_count"] == 29
    assert result.json()["longest_contiguous"] == 20
