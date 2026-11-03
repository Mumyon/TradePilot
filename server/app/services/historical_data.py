"""Strict, auditable ingestion of provider-returned KRW 5-minute observations.

No resampling of daily/close-only data, interpolation, or manufactured OHLCV.
Archived provider responses and normalized data have separate hashes.
"""

import copy
import gzip
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from ..ml import pipeline as ml
from ..models import ReplayCase
from .orders import lock_user

KST = ZoneInfo("Asia/Seoul")
BUNDLE = Path(__file__).resolve().parents[1] / "data" / "historical" / "2026-10-20"
FIELDS = ["opened_at", "open_won", "high_won", "low_won", "close_won", "volume"]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def row_hash(rows):
    return sha(json.dumps(rows, sort_keys=True).encode())


def parse_yahoo(raw: bytes, symbol: str, *, through: str):
    doc = json.loads(raw)
    if doc.get("chart", {}).get("error") or not doc.get("chart", {}).get("result"):
        raise ValueError("Provider did not return observations")
    result = doc["chart"]["result"][0]
    meta = result["meta"]
    if (
        meta.get("symbol") != symbol + ".KS"
        or meta.get("currency") != "KRW"
        or meta.get("dataGranularity") != "5m"
        or meta.get("exchangeTimezoneName") != "Asia/Seoul"
    ):
        raise ValueError("Expected matching KRX/KRW/Asia-Seoul/5m metadata")
    quote = result["indicators"]["quote"][0]
    timestamps = result["timestamp"]
    if any(len(quote[k]) != len(timestamps) for k in ("open", "high", "low", "close", "volume")):
        raise ValueError("Mismatched provider arrays")
    rows, excluded, seen = [], dict(after_cutoff=0, non_regular=0, null_ohlcv=0), set()
    for index, value in enumerate(timestamps):
        at = datetime.fromtimestamp(value, UTC)
        local = at.astimezone(KST)
        if local.date().isoformat() > through:
            excluded["after_cutoff"] += 1
            continue
        if (
            local.second
            or local.microsecond
            or local.minute % 5
            or local.weekday() > 4
            or not 9 * 60 <= local.hour * 60 + local.minute <= 15 * 60 + 25
        ):
            excluded["non_regular"] += 1
            continue
        values = [quote[k][index] for k in ("open", "high", "low", "close", "volume")]
        if any(v is None for v in values):
            excluded["null_ohlcv"] += 1
            continue
        if at in seen:
            raise ValueError("Duplicate observation timestamp")
        seen.add(at)
        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v != int(v)
            for v in values
        ):
            raise ValueError("KRW OHLCV must be finite integer values; rounding is not allowed")
        values = list(map(int, values))
        rows.append(dict(zip(FIELDS, [at.isoformat(), *values])))
    as_bars = to_bars(rows)
    ml.validate_bars(as_bars)
    if not rows:
        raise ValueError("No usable observations")
    return rows, dict(
        raw_sha256=sha(raw),
        exclusions=excluded,
        rows=len(rows),
        volume_zero_rows=sum(r["volume"] == 0 for r in rows),
        first_bar=rows[0]["opened_at"],
        last_bar=rows[-1]["opened_at"],
    )


def to_bars(rows):
    return [
        ml.Bar(datetime.fromisoformat(r["opened_at"]), *(r[k] for k in FIELDS[1:])) for r in rows
    ]


def coverage(rows, day):
    selected = [
        r
        for r in rows
        if datetime.fromisoformat(r["opened_at"]).astimezone(KST).date().isoformat() == day
    ]
    opening = datetime.fromisoformat(day + "T09:00:00+09:00")
    expected = [(opening + timedelta(minutes=5 * i)).astimezone(UTC).isoformat() for i in range(78)]
    actual = {r["opened_at"] for r in selected}
    return dict(
        date=day,
        expected_regular_bars=78,
        available_bars=len(selected),
        missing_open_times=[s for s in expected if s not in actual],
        zero_volume_bars=sum(r["volume"] == 0 for r in selected),
    )


def load_bundle(folder=None):
    folder = folder or BUNDLE
    manifest = json.loads((folder / "manifest.json").read_text())
    cases = []
    # Verify original archives too: no silently detached normalized data.
    for source in manifest["sources"]:
        raw = gzip.decompress((folder / source["archive"]).read_bytes())
        if sha(raw) != source["sha256"]:
            raise ValueError("Historical source archive hash mismatch")
    for entry in manifest["cases"]:
        raw = (folder / entry["file"]).read_bytes()
        if sha(raw) != entry["sha256"]:
            raise ValueError("Historical case file hash mismatch")
        data = json.loads(raw)
        if row_hash(data["rows"]) != data["config"]["data_sha256"]:
            raise ValueError("Historical rows hash mismatch")
        ml.validate_bars(to_bars(data["rows"]))
        config = data["config"]
        if (
            config["data_kind"] != "historical"
            or config["interval"] != "5m"
            or not 35 <= config["start"] < len(data["rows"]) - 1
        ):
            raise ValueError("Invalid historical case bounds")
        artifact = None
        if entry.get("model_file"):
            model_path = folder / entry["model_file"]
            if sha(model_path.read_bytes()) != entry["model_sha256"]:
                raise ValueError("Historical model hash mismatch")
            artifact = ml.load_artifact(model_path)
            if (
                artifact["symbol"] != config["symbol"]
                or artifact["data_kind"] != "historical"
                or artifact["source"] != config["provider"]
                or artifact["csv_sha256"] != row_hash(data["rows"][: config["start"]])
                or datetime.fromisoformat(artifact["data_end"])
                > datetime.fromisoformat(config["replay_from"])
            ):
                raise ValueError("Historical model input mismatch or lookahead")
        cases.append((config, data["rows"], artifact))
    return cases


def install(db, uid):
    # Explicit POST, local verified archives only; opening the app never scrapes a provider.
    lock_user(db, uid)
    try:
        bundle = load_bundle()
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(
            503, "실제 사례 파일 검증에 실패했습니다. 서버 자료를 확인하세요."
        ) from exc
    existing = db.scalars(select(ReplayCase).where(ReplayCase.user_id == uid)).all()
    ids, created = [], 0
    for config, rows, artifact in bundle:
        found = next(
            (
                c
                for c in existing
                if c.config.get("catalog_id") == config["catalog_id"]
                and c.config["data_sha256"] == config["data_sha256"]
            ),
            None,
        )
        if found:
            ids.append(found.id)
            continue
        if len(existing) + created >= 50:
            raise HTTPException(409, "사용자당 사례 50개 한도에 도달했습니다.")
        c = ReplayCase(
            user_id=uid,
            config=copy.deepcopy(config),
            rows=copy.deepcopy(rows),
            artifact=copy.deepcopy(artifact),
        )
        db.add(c)
        db.flush()
        ids.append(c.id)
        created += 1
    return dict(case_ids=ids, created=created, source="Yahoo Finance · archived 5m OHLCV")
