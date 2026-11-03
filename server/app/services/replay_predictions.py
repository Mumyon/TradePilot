"""Review frozen order-check predictions using only bars revealed during the run."""

from datetime import datetime, timedelta

from ..ml.pipeline import LABELS, label

BAR = timedelta(minutes=5)
HORIZON = timedelta(hours=1)
VERSION = "replay-prediction-review-v1"


def review(case, state):
    # Never score against the hidden suffix, even after an early finish.
    visible = case.rows[: state["cursor"] + 1]
    by_close = {datetime.fromisoformat(r["opened_at"]) + BAR: r for r in visible}
    latest = max(by_close)
    grouped = {}
    unavailable = 0
    for check in state["checks"]:
        snapshot = check["analysis"].get("prediction", {})
        if snapshot.get("status") != "available":
            unavailable += 1
            continue
        at = datetime.fromisoformat(snapshot["as_of"])
        key = (snapshot["model_version"], at)
        if key in grouped:
            grouped[key]["check_ids"].append(check["check_id"])
            continue
        target = at + HORIZON
        outcome = dict(status="pending", target_at=target.isoformat(), correct=None)
        base = by_close.get(at)
        if base is None:
            outcome.update(status="unavailable", reason="예측 기준 봉 없음")
        elif latest >= target:
            window = [by_close.get(at + BAR * step) for step in range(1, 13)]
            if any(r is None for r in window):
                outcome.update(status="unavailable", reason="1시간 평가 구간의 5분봉 결측")
            else:
                price, future = base["close_won"], window[-1]["close_won"]
                actual = LABELS[label(price, future)]
                outcome.update(
                    status="resolved",
                    base_price_won=price,
                    target_price_won=future,
                    actual_direction=actual,
                    return_percent=(future - price) * 100 / price,
                    correct=None
                    if snapshot["direction"] == "abstain"
                    else snapshot["direction"] == actual,
                )
        grouped[key] = dict(check_ids=[check["check_id"]], prediction=snapshot, outcome=outcome)
    observations = list(grouped.values())
    scored = [x for x in observations if x["outcome"]["correct"] is not None]
    correct = sum(x["outcome"]["correct"] for x in scored)
    return dict(
        schema=VERSION,
        policy="same_model_and_as_of_once; revealed_contiguous_12_bars; +/-0.5%; abstain_excluded",
        summary=dict(
            unique_predictions=len(observations),
            unavailable_checks=unavailable,
            resolved=sum(x["outcome"]["status"] == "resolved" for x in observations),
            pending=sum(x["outcome"]["status"] == "pending" for x in observations),
            unavailable=sum(x["outcome"]["status"] == "unavailable" for x in observations),
            abstained=sum(x["prediction"]["direction"] == "abstain" for x in observations),
            evaluated=len(scored),
            correct=correct,
            accuracy=correct / len(scored) if scored else None,
        ),
        observations=observations,
    )
