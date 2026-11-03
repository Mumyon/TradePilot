"""Build a fixed local research snapshot from downloaded provider responses.

No network calls. No invented OHLCV. Existing output folders are rejected.
Example: PYTHONPATH=. .venv/bin/python tool/build_historical_catalog.py \
  --yahoo /tmp/tradepilot-samsung-5m.json --naver /tmp/tradepilot-samsung-daily.xml \
  --output app/data/historical/2026-10-20
"""

import argparse
import csv
import gzip
import io
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from app.ml import pipeline as ml
from app.services import historical_data as data

CASES = [
    ("2026-07-29", "삼성전자 · 2026-07-29 실제 5분봉"),
    ("2026-08-21", "삼성전자 · 2026-08-21 실제 5분봉"),
    ("2026-10-13", "삼성전자 · 2026-10-13 실제 5분봉"),
    ("2026-10-15", "삼성전자 · 2026-10-15 실제 5분봉"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--yahoo", type=Path, required=True)
    parser.add_argument("--naver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Use a NEW output directory; frozen snapshots must not be overwritten")
    raw, daily_raw = args.yahoo.read_bytes(), args.naver.read_bytes()
    rows, info = data.parse_yahoo(raw, "005930", through="2026-10-19")
    daily = {}
    for item in ET.fromstring(daily_raw.decode("euc-kr")).iter("item"):
        date, *v = item.attrib["data"].split("|")
        daily[date] = list(map(int, v))
    args.output.mkdir(parents=True)
    manifest = dict(
        schema=1,
        retrieved_on="2026-10-20",
        built_at=datetime.now(UTC).isoformat(),
        parser="yahoo-krw-5m-v1",
        sources=[],
        cases=[],
        quality=info,
    )
    for name, content, url, purpose in [
        (
            "yahoo-005930-5m.json.gz",
            raw,
            "https://query1.finance.yahoo.com/v8/finance/chart/005930.KS?interval=5m&range=60d&includePrePost=false",
            "실제 5분봉 OHLCV 원본",
        ),
        (
            "naver-005930-day.xml.gz",
            daily_raw,
            "https://fchart.stock.naver.com/sise.nhn?symbol=005930&timeframe=day&count=3000&requestType=0",
            "사례 당일 시가·고가·저가 대조 전용. 재생·AI 입력으로 사용하지 않음",
        ),
    ]:
        (args.output / name).write_bytes(gzip.compress(content, mtime=0))
        manifest["sources"].append(
            dict(archive=name, sha256=data.sha(content), url=url, purpose=purpose)
        )
    for day, name in CASES:
        # Preserve all available earlier real bars; truncate at the selected day.
        selected = [
            r
            for r in rows
            if datetime.fromisoformat(r["opened_at"]).astimezone(data.KST).date().isoformat() <= day
        ]
        first = day + "T09:00:00+09:00"
        opening = datetime.fromisoformat(first).astimezone(UTC).isoformat()
        start = next(i for i, r in enumerate(selected) if r["opened_at"] == opening)
        visible_day = selected[start:]
        check_daily = daily[day.replace("-", "")]
        checks = dict(
            first_open_matches=visible_day[0]["open_won"] == check_daily[0],
            highs_within_daily=max(r["high_won"] for r in visible_day) <= check_daily[1],
            lows_within_daily=min(r["low_won"] for r in visible_day) >= check_daily[2],
        )
        if not all(checks.values()):
            raise ValueError(f"{day}: independent daily range cross-check failed")
        cid = "yahoo-005930-" + day + "-v1"
        config = dict(
            catalog_id=cid,
            name=name,
            symbol="005930",
            provider="yahoo-finance-5m",
            data_kind="historical",
            interval="5m",
            event_key="observed_" + day,
            source_url=manifest["sources"][0]["url"],
            source_archives=manifest["sources"],
            retrieved_on="2026-10-20",
            start=start,
            bar_count=len(selected),
            replay_from=opening,
            end=selected[-1]["opened_at"],
            data_sha256=data.row_hash(selected),
            provenance="Yahoo Finance 실제 5분봉 · 2026-10-20 수집",
            coverage=data.coverage(selected, day),
            daily_cross_check=dict(
                checks=checks,
                naver_ohlcv=check_daily,
                note="일봉으로 일부 범위 대조만 수행. 모든 분봉의 정확성 인증은 아님",
            ),
            data_notice="09:00~14:55 제공분만 재생합니다. 결측 봉은 보간하지 않습니다. "
            "15:00~15:25 및 일부 봉이 미제공되어 전장 재현이 아닙니다. "
            "0 거래량은 제공값 그대로이며 실제 무거래로 확정하지 않습니다.",
            selection_policy=(
                "최근 제공 범위에서 사후 선택한 변동 사례. 대표성/성과 추정용 무작위 표본 아님"
            ),
            adjustment_policy=(
                "제공자 OHLCV 그대로. 수정주가 여부 및 전 봉의 체결자료 대조는 별도 미확인"
            ),
        )
        output = dict(config=config, rows=selected)
        filename = cid + ".json"
        body = json.dumps(output, ensure_ascii=False, indent=2).encode()
        entry = dict(file=filename, sha256=data.sha(body))
        try:
            artifact = ml.train(
                data.to_bars(selected[:start]),
                "005930",
                config["provider"],
                "historical",
                data.row_hash(selected[:start]),
            )
        except ValueError as exc:
            config["training_status"] = "unavailable"
            config["training_note"] = str(exc)
        else:
            model_name = cid + "-model.json"
            model_raw = json.dumps(artifact, ensure_ascii=False, indent=2).encode()
            (args.output / model_name).write_bytes(model_raw)
            entry.update(model_file=model_name, model_sha256=data.sha(model_raw))
            config["training_status"] = (
                "passed" if artifact["quality_gate_passed"] else "failed_gate"
            )
        body = json.dumps(output, ensure_ascii=False, indent=2).encode()
        entry["sha256"] = data.sha(body)
        (args.output / filename).write_bytes(body)
        csv_out = io.StringIO()
        writer = csv.DictWriter(csv_out, fieldnames=data.FIELDS)
        writer.writeheader()
        writer.writerows(selected)
        (args.output / (cid + ".csv")).write_text(csv_out.getvalue())
        manifest["cases"].append(entry)
        print(day, "rows", len(selected), "replay", len(visible_day), config["training_status"])
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    data.load_bundle(args.output)
    print("Archive, row and model integrity verified")


if __name__ == "__main__":
    main()
