from collections import Counter
from datetime import timedelta

from sqlalchemy import select

from ..models import Fill, Order, OrderCheck, PredictionRecord, now

FEEDBACK = {
    "fomo": "급등 구간 점검 기록이 있습니다. 급등 전에 저장한 진입 가격 범위를 먼저 확인하세요.",
    "panic": "급락·평가손실 구간 매도 점검 기록이 있습니다. 사전 손절·분할청산 기준과 비교하세요.",
    "revenge": "연속 손실 이후 매수 경고가 있습니다. 거래 이유와 손실한도를 다시 확인하세요.",
    "overtrading": "단시간 반복 주문 경고가 있습니다. 거래 간격과 사전 분할 계획을 확인하세요.",
    "plan": "계획 조건과 다른 주문이 있습니다. 가격 범위·방향·금액 한도를 점검하세요.",
}


def report(db, user_id, days=30, offset=0):
    at = now()
    start = at - timedelta(days=days)
    orders = db.scalars(
        select(Order)
        .where(Order.user_id == user_id, Order.created_at >= start, Order.created_at <= at)
        .order_by(Order.created_at.desc(), Order.id.desc())
    ).all()
    checks = db.scalars(
        select(OrderCheck).where(
            OrderCheck.user_id == user_id,
            OrderCheck.created_at >= start,
            OrderCheck.created_at <= at,
        )
    ).all()
    fills = {
        f.order_id: f
        for f in db.scalars(
            select(Fill).where(
                Fill.user_id == user_id, Fill.created_at >= start, Fill.created_at <= at
            )
        )
    }
    warnings = Counter()
    decisions = Counter()
    for check in checks:
        behavior = check.analysis.get("behavior", {})
        hits = [i["code"] for i in behavior.get("items", []) if i["status"] == "hit"]
        warnings.update(hits)
        if hits:
            decisions[check.decision] += 1
    evaluated = adherent = unregistered = unavailable = 0
    prediction_ids = set()
    for order in orders:
        preflight = order.analysis.get("preflight", {})
        if order.status == "filled":
            plan = (order.analysis.get("submission") or preflight).get("plan")
            if not plan:
                unregistered += 1
            elif plan.get("status") in ("clear", "hit"):
                evaluated += 1
                adherent += plan["status"] == "clear"
            else:
                unavailable += 1
        prediction = preflight.get("prediction", {})
        if prediction.get("status") == "available":
            prediction_ids.add(prediction["prediction_id"])
    records = (
        {
            r.id: r
            for r in db.scalars(
                select(PredictionRecord).where(PredictionRecord.id.in_(prediction_ids))
            )
        }
        if prediction_ids
        else {}
    )
    resolved = [r for r in records.values() if r.outcome and r.outcome.get("correct") is not None]
    correct = sum(r.outcome["correct"] for r in resolved)
    sells = [f for f in fills.values() if f.side == "sell"]
    items = []
    for order in orders[offset : offset + 50]:
        preflight = order.analysis.get("preflight", {})
        prediction = preflight.get("prediction", {})
        record = records.get(prediction.get("prediction_id"))
        fill = fills.get(order.id)
        items.append(
            dict(
                order_id=order.id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                limit_price_won=str(order.limit_price_won),
                status=order.status,
                created_at=order.created_at,
                reason=order.reason,
                review_note=order.review_note,
                review_updated_at=order.review_updated_at,
                trade_reason=order.analysis.get("trade_reason", ""),
                plan=preflight.get("plan"),
                behavior=preflight.get("behavior"),
                risk=preflight.get("risk"),
                final_risk=(order.analysis.get("submission") or {}).get("risk"),
                blocking_reasons=order.analysis.get("blocking_reasons", []),
                prediction=prediction or dict(status="unavailable", message="당시 예측 기록 없음"),
                prediction_outcome=record.outcome
                if record and record.outcome
                else dict(status="pending"),
                fill=None
                if fill is None
                else dict(
                    quantity=fill.quantity,
                    price_won=str(fill.price_won),
                    fee_won=str(fill.fee_won),
                    realized_pnl_won=None
                    if fill.realized_pnl_won is None
                    else str(fill.realized_pnl_won),
                    created_at=fill.created_at,
                ),
            )
        )
    feedback = [FEEDBACK[code] for code, _ in warnings.most_common(3)]
    if unregistered:
        feedback.append(f"계획 미등록 체결 {unregistered}건은 원칙 준수율 계산에서 제외했습니다.")
    return dict(
        window=dict(start=start, end=at, days=days),
        items=items,
        total_orders=len(orders),
        next_offset=offset + 50 if offset + 50 < len(orders) else None,
        summary=dict(
            filled_orders=sum(o.status == "filled" for o in orders),
            realized_pnl_won=str(sum(f.realized_pnl_won or 0 for f in sells)),
            pnl_complete=all(f.realized_pnl_won is not None for f in sells),
            plan_evaluated=evaluated,
            plan_adherent=adherent,
            plan_unregistered=unregistered,
            plan_unavailable=unavailable,
            plan_compliance=None if not evaluated else adherent / evaluated,
            warning_counts=dict(warnings),
            warning_decisions=dict(decisions),
            prediction_evaluated=len(resolved),
            prediction_correct=correct,
            prediction_accuracy=None if not resolved else correct / len(resolved),
            prediction_abstained=sum(
                r.data.get("direction") == "abstain" for r in records.values()
            ),
            prediction_pending=sum(not r.outcome for r in records.values()),
        ),
        feedback=feedback
        or ["평가 가능한 기록을 쌓으면 거래 원칙과 반복 경고에 대한 피드백을 제공합니다."],
        notes=[
            "원칙 준수율: 기간 내 체결 주문 중 선택한 계획을 평가할 수 있는 주문 기준",
            "경고 횟수: 주문 접수 횟수가 아닌 점검 시도 횟수; 보류·진행·미결정을 구분",
            "예측 적중: 중복 예측 ID를 제외한 1시간 방향 결과; 보유 기간 손익과 별개",
            "거절·취소·미체결 주문은 체결 건수 및 원칙 준수율에 포함하지 않음",
        ],
    )
