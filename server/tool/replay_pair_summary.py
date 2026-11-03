"""Descriptive paired analysis of exported replay JSON. No generated observations.

PYTHONPATH=. .venv/bin/python tool/replay_pair_summary.py on.json off.json --output pairs.json
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from types import SimpleNamespace

from app.services.replay import digest, summary


def summarize_exports(documents, *, include_synthetic=False):
    unique, groups = {}, defaultdict(list)
    duplicates = 0
    for doc in documents:
        key = (doc["participant_id"], doc["run_id"])
        if key in unique:
            if unique[key] != doc:
                raise ValueError("같은 실행 ID의 서로 다른 내보내기 파일이 있습니다.")
            duplicates += 1
            continue
        unique[key] = doc
        if digest(doc["case_rows"]) != doc["case"]["data_sha256"]:
            raise ValueError("사례 원자료와 저장된 해시가 다릅니다.")
        if not 0 <= doc["state"]["cursor"] < len(doc["case_rows"]):
            raise ValueError("관찰 구간이 사례 범위를 벗어납니다.")
        groups[(doc["participant_id"], doc["state"]["pair_id"])].append(doc)
    pairs, excluded = [], []
    for (participant, pair_id), runs in groups.items():
        reason = None
        runs.sort(key=lambda d: d["state"]["sequence"])
        if len(runs) != 2 or [d["state"]["sequence"] for d in runs] != [1, 2]:
            reason = "ON/OFF 두 실행이 완성된 쌍이 아님"
        elif any(not d["state"]["finished"] for d in runs):
            reason = "종료되지 않은 실행"
        elif {d["state"]["pilot_enabled"] for d in runs} != {True, False}:
            reason = "서로 반대인 Pilot 조건이 아님"
        elif runs[1]["state"].get("paired_run_id") != runs[0]["run_id"]:
            reason = "첫 실행과 두 번째 실행의 연결 불일치"
        elif any(d["case"]["data_kind"] != "historical" for d in runs) and not include_synthetic:
            reason = "실제 과거 데이터가 아닌 연습 자료"
        elif not runs[0]["state"].get("behavior_policy"):
            reason = "실험 시작 시 규칙 스냅샷 없음"
        elif any(runs[0][k] != runs[1][k] for k in ("case", "model")):
            reason = "사례 또는 모델이 다름"
        elif any(
            runs[0]["state"].get(k) != runs[1]["state"].get(k)
            for k in (
                "comparison_key",
                "config",
                "plan",
                "behavior_policy",
                "cursor",
                "allocation_method",
                "condition_order",
                "allocation_at",
            )
        ):
            reason = "설정·계획·규칙·배정 또는 관찰 종료 구간이 다름"
        if reason:
            excluded.append(dict(participant_id=participant, pair_id=pair_id, reason=reason))
            continue
        metrics = {}
        for d in runs:
            case = SimpleNamespace(rows=d["case_rows"], config=d["case"])
            # Recompute from saved decisions instead of trusting an edited summary field.
            metrics["on" if d["state"]["pilot_enabled"] else "off"] = summary(case, d["state"])
        on, off = metrics["on"], metrics["off"]
        a, b = on["plan_compliance_rate"], off["plan_compliance_rate"]
        pairs.append(
            dict(
                participant_id=participant,
                pair_id=pair_id,
                data_kind=runs[0]["case"]["data_kind"],
                condition_order=runs[0]["state"].get("condition_order"),
                allocation_method=runs[0]["state"].get("allocation_method"),
                plan_compliance_difference_pp=(a - b) * 100
                if a is not None and b is not None
                else None,
                rule_qualified_submissions_difference=(
                    on["rule_qualified_submissions"] - off["rule_qualified_submissions"]
                ),
                metrics=metrics,
            )
        )
    participant_deltas = defaultdict(list)
    for pair in pairs:
        if pair["plan_compliance_difference_pp"] is not None:
            participant_deltas[(pair["data_kind"], pair["participant_id"])].append(
                pair["plan_compliance_difference_pp"]
            )
    cohorts = []
    for kind in sorted({p["data_kind"] for p in pairs}):
        means = [mean(v) for (k, _), v in participant_deltas.items() if k == kind]
        cohorts.append(
            dict(
                data_kind=kind,
                pairs=sum(p["data_kind"] == kind for p in pairs),
                participants=len({p["participant_id"] for p in pairs if p["data_kind"] == kind}),
                participants_with_plan_comparison=len(means),
                mean_participant_plan_difference_pp=mean(means) if means else None,
            )
        )
    return dict(
        schema="replay-pairs-v1",
        duplicate_files_ignored=duplicates,
        pairs=pairs,
        excluded=excluded,
        cohorts=cohorts,
        note="기술통계만 제공. 같은 참가자의 쌍별 차이를 먼저 평균합니다. "
        "점검을 독립 표본으로 세지 않습니다. 배정·사례 선택·학습효과를 통제한 "
        "인과 추정이나 유의성 검정이 아닙니다. 해시는 출처의 진위를 인증하지 않습니다.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--include-synthetic", action="store_true")
    args = parser.parse_args()
    result = summarize_exports(
        [json.loads(p.read_text(encoding="utf-8-sig")) for p in args.files],
        include_synthetic=args.include_synthetic,
    )
    # Never overwrite previous research outputs.
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"비교 가능 {len(result['pairs'])}쌍 · 제외 {len(result['excluded'])}쌍")


if __name__ == "__main__":
    main()
