"""Real archived observations, absence of lookahead and conservative gap execution."""

import copy
import gzip
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_replay import act, key, order

from app.models import ReplayCase, ReplayRun, User
from app.services import historical_data as data
from app.services import replay


def provider():
    return json.loads(gzip.decompress((data.BUNDLE / "yahoo-005930-5m.json.gz").read_bytes()))


def test_archived_rows_are_exact_provider_observations_and_models_use_only_prefix():
    raw = provider()
    source = raw["chart"]["result"][0]
    quote = source["indicators"]["quote"][0]
    observations = dict(
        zip(
            source["timestamp"],
            zip(*(quote[k] for k in ("open", "high", "low", "close", "volume"))),
        )
    )
    bundle = data.load_bundle()
    assert len(bundle) == 4
    assert [c["training_status"] for c, _, _ in bundle] == [
        "unavailable",
        "failed_gate",
        "passed",
        "passed",
    ]
    for config, rows, model in bundle:
        assert config["interval"] == "5m" and config["data_kind"] == "historical"
        assert config["coverage"]["available_bars"] == len(rows) - config["start"]
        assert config["coverage"]["missing_open_times"]  # Never pretend a full session.
        for row in rows:
            assert (
                tuple(row[k] for k in data.FIELDS[1:])
                == observations[int(replay.stamp(row["opened_at"]).timestamp())]
            )
        if model:
            assert model["csv_sha256"] == data.row_hash(rows[: config["start"]])
            assert replay.stamp(model["data_end"]) <= replay.stamp(config["replay_from"])


@pytest.mark.parametrize("mutation", ["daily", "fraction", "duplicate"])
def test_parser_rejects_wrong_interval_or_fabricating_prices(mutation):
    doc = provider()
    result = doc["chart"]["result"][0]
    if mutation == "daily":
        result["meta"]["dataGranularity"] = "1d"
    elif mutation == "fraction":
        result["indicators"]["quote"][0]["open"][0] += 0.5
    else:
        result["timestamp"][1] = result["timestamp"][0]
    with pytest.raises(ValueError):
        data.parse_yahoo(json.dumps(doc).encode(), "005930", through="2026-10-19")


def test_parser_leaves_null_gaps_and_excludes_unfinished_day():
    doc = provider()
    result = doc["chart"]["result"][0]
    result["indicators"]["quote"][0]["close"][1] = None
    missing = result["timestamp"][1]
    rows, quality = data.parse_yahoo(json.dumps(doc).encode(), "005930", through="2026-10-19")
    assert missing not in [int(replay.stamp(r["opened_at"]).timestamp()) for r in rows]
    assert quality["exclusions"]["null_ohlcv"] == 17
    assert quality["exclusions"]["after_cutoff"] == 37
    assert rows[-1]["opened_at"].startswith("2026-10-19")


def test_source_tampering_fails_closed(tmp_path):
    manifest = json.loads((data.BUNDLE / "manifest.json").read_text())
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / manifest["sources"][0]["archive"]).write_bytes(gzip.compress(b"changed"))
    with pytest.raises(ValueError, match="archive hash mismatch"):
        data.load_bundle(tmp_path)


def test_install_preserves_old_runs_and_real_fills_export(service):
    client, sessions, uid, _ = service
    old = client.post("/v1/replay/practice").json()
    old_run = client.post(
        f"/v1/replay/cases/{old['id']}/runs", json={"request_id": key(), "pilot_enabled": True}
    ).json()
    installed = client.post("/v1/replay/historical")
    assert installed.status_code == 200, installed.text
    assert installed.json()["created"] == 4
    assert client.post("/v1/replay/historical").json()["created"] == 0
    hub = client.get("/v1/replay").json()
    assert len(hub["cases"]) == 5 and len(hub["runs"]) == 1
    assert hub["cases"][0]["data_kind"] == "historical"
    assert client.get(f"/v1/replay/runs/{old_run['id']}").json() == old_run
    c = next(c for c in hub["cases"] if c.get("catalog_id") == "yahoo-005930-2026-10-13-v1")
    assert "daily_cross_check" not in c and "rows" not in c and "artifact" not in c
    run = client.post(
        f"/v1/replay/cases/{c['id']}/runs", json={"request_id": key(), "pilot_enabled": True}
    ).json()
    assert run["interval"] == "5m" and run["data_kind"] == "historical"
    assert run["visible_bars"] == c["preview"] and len(run["visible_bars"]) == 35
    assert run["prediction"]["status"] == "unavailable"  # Overnight gap, not 35 continuous bars.
    with sessions.begin() as db:
        original_cash = db.get(User, uid).cash_won
        case = db.get(ReplayCase, c["id"])
        next_open = case.rows[run["cursor"] + 1]["open_won"]
    run = order(client, run, price=next_open + 500)
    run = act(client, run, "advance")
    assert run["orders"][0]["fill_price"] == next_open
    assert run["cash_won"] == 10_000_000 - next_open - replay.fee(next_open)
    assert client.get(f"/v1/replay/runs/{run['id']}/export").status_code == 409
    run = act(client, run, "finish")
    evidence = client.get(f"/v1/replay/runs/{run['id']}/export").json()["evidence"]
    assert data.row_hash(evidence["case_rows"]) == c["data_sha256"]
    assert evidence["case"]["daily_cross_check"]["checks"]["first_open_matches"]
    assert evidence["case"]["source_archives"][0]["sha256"] == data.sha(
        gzip.decompress((data.BUNDLE / "yahoo-005930-5m.json.gz").read_bytes())
    )
    with sessions.begin() as db:
        assert db.get(User, uid).cash_won == original_cash


def test_real_gap_cancels_orders_and_abstains(service):
    client, sessions, uid, _ = service
    client.post("/v1/replay/historical")
    c = next(
        c
        for c in client.get("/v1/replay").json()["cases"]
        if c["catalog_id"] == "yahoo-005930-2026-07-29-v1"
    )
    run = client.post(
        f"/v1/replay/cases/{c['id']}/runs", json={"request_id": key(), "pilot_enabled": True}
    ).json()
    with sessions.begin() as db:
        case = db.get(ReplayCase, c["id"])
        before_gap = next(
            i
            for i in range(case.config["start"], len(case.rows) - 1)
            if replay.stamp(case.rows[i + 1]["opened_at"]) - replay.stamp(case.rows[i]["opened_at"])
            != timedelta(minutes=5)
        )
        r = db.get(ReplayRun, run["id"])
        r.state = {**r.state, "cursor": before_gap}
        limit = max(case.rows[before_gap]["close_won"], case.rows[before_gap + 1]["open_won"]) + 500
    run = client.get(f"/v1/replay/runs/{run['id']}").json()
    run = order(client, run, price=limit)
    run = act(client, run, "advance")
    assert run["quantity"] == 0 and run["cash_won"] == 10_000_000
    assert run["orders"][0]["status"] == "cancelled"
    assert "fill_price" not in run["orders"][0]
    assert "시세 단절" in run["market_notice"]
    assert run["prediction"]["status"] == "unavailable"
    run = act(client, run, "finish")
    exported = client.get(f"/v1/replay/runs/{run['id']}/export").json()["evidence"]
    assert len(exported["state"]["market_gaps"]) == 1


def test_real_model_gate_horizon_and_unseen_prices():
    bundle = data.load_bundle()
    for config, rows, model in bundle:
        case = SimpleNamespace(config=config, rows=rows, artifact=model)
        # 35 completed contiguous bars by 11:55 on days with full morning coverage.
        cursor = config["start"] + 34
        result = replay.prediction(case, {"cursor": cursor})
        if config["training_status"] == "passed" and config["coverage"]["available_bars"] == 72:
            assert result["status"] == "available"
            assert result["data_kind"] == "historical"
            changed = copy.deepcopy(rows)
            for r in changed[cursor + 1 :]:
                r["close_won"] *= 2
            case.rows = changed
            assert replay.prediction(case, {"cursor": cursor}) == result
            case.rows = rows
            assert replay.prediction(case, {"cursor": len(rows) - 10})["status"] == "unavailable"
        elif config["training_status"] == "failed_gate":
            assert result["status"] == "unavailable" and "검증 기준 미달" in result["message"]
        elif model is None:
            assert result["status"] == "unavailable"


def test_real_10_minute_move_triggers_pilot_but_is_hidden_in_off(service):
    client, sessions, uid, _ = service
    client.post("/v1/replay/historical")
    case = next(
        c
        for c in client.get("/v1/replay").json()["cases"]
        if c["catalog_id"] == "yahoo-005930-2026-07-29-v1"
    )
    with sessions.begin() as db:
        c = db.get(ReplayCase, case["id"])
        cursor = next(
            i for i, r in enumerate(c.rows) if r["opened_at"] == "2026-07-29T04:50:00+00:00"
        )
    for enabled in (True, False):
        run = client.post(
            f"/v1/replay/cases/{case['id']}/runs",
            json={"request_id": key(), "pilot_enabled": enabled},
        ).json()
        with sessions.begin() as db:
            r = db.get(ReplayRun, run["id"])
            r.state = {**r.state, "cursor": cursor}
        run = act(client, run, "check", side="buy", quantity=1, limit_price_won=198400)
        check = run["action_result"]
        assert check["analysis"]["behavior"]["score"] == (30 if enabled else 0)
        assert "shadow" not in str(run)
        run = act(client, run, "presented", check_id=check["check_id"])
        run = act(client, run, "defer", check_id=check["check_id"])
        run = act(client, run, "finish")
        assert run["summary"]["rule_qualified_checks"] == 1
        assert run["summary"]["warned_deferrals"] == (1 if enabled else 0)
