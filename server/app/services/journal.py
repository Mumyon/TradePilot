import re
from collections import Counter
from datetime import timedelta

from sqlalchemy import select

from ..models import AIReview, Fill, Order, OrderCheck, PredictionRecord, Symbol, now
from . import journal_samples
from .ai_review import status_view

FEEDBACK = {
    "fomo": "급등 구간 점검 기록이 있습니다. 급등 전에 저장한 진입 가격 범위를 먼저 확인하세요.",
    "panic": "급락·평가손실 구간 매도 점검 기록이 있습니다. 사전 손절·분할청산 기준과 비교하세요.",
    "revenge": (
        "연속 손실 이후 매수 경고가 있습니다. 거래 이유와 사전에 세운 매매 계획을 다시 확인하세요."
    ),
    "overtrading": "단시간 반복 주문 경고가 있습니다. 거래 간격과 사전 분할 계획을 확인하세요.",
    "plan": "계획 조건과 다른 주문이 있습니다. 가격 범위·방향·금액 한도를 점검하세요.",
}


def _historical_review(review, decision_at):
    if review is None or review.completed_at is None or review.completed_at > decision_at:
        return None
    view = status_view(review)
    return {
        key: view[key]
        for key in ("status", "result", "search", "analysis_as_of", "quote_context", "completed_at")
    }


def _advice_comparison(advice, actual):
    if not advice or advice["status"] != "available":
        return None
    result = advice["result"] or {}
    judgment = result.get("judgment")
    if judgment is None:
        # Earlier web reports can be compared only when their conclusion is explicit.
        body = re.sub(r"[*`]", "", result.get("body") or "")
        match = re.search(
            r"(?m)^\s*(?:#+\s*)?(?:[0-9]+[.)]\s*)?최종 판단\s*[:：]\s*"
            r"(매수|매도|관망|보류|데이터 부족)\s*$",
            body,
        )
        judgment = match[1] if match else None
    if judgment not in {"매수", "매도", "관망", "보류", "데이터 부족"}:
        return None
    matched = (
        None
        if judgment == "데이터 부족" or actual is None
        else judgment == actual or (actual == "보류" and judgment == "관망")
    )
    return dict(advice=judgment, actual=actual, matched=matched)


def report(db, user_id, days=30, offset=0, *, include_pretrade=False, include_ai=False):
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
    page = orders[offset : offset + 50]
    deferred = []
    reviews = {}
    order_checks = {}
    filled_orders = [o for o in orders if o.status == "filled" and o.id in fills]
    comparison_counts = Counter()
    if include_pretrade:
        deferred = sorted(
            (
                c
                for c in checks
                if c.origin == "manual" and c.decision == "dismissed" and c.decided_at
            ),
            key=lambda c: (c.decided_at, c.id),
            reverse=True,
        )
        if include_ai and (page or filled_orders):
            order_checks = {
                c.submitted_order_id: c.id
                for c in db.scalars(
                    select(OrderCheck).where(
                        OrderCheck.user_id == user_id,
                        OrderCheck.submitted_order_id.in_(
                            list({order.id for order in page + filled_orders})
                        ),
                    )
                )
            }
        check_ids = set(order_checks.values())
        check_ids.update(c.id for c in deferred)
        if include_ai and check_ids:
            reviews = {
                r.check_id: r
                for r in db.scalars(
                    select(AIReview).where(
                        AIReview.user_id == user_id, AIReview.check_id.in_(check_ids)
                    )
                )
            }

    def order_advice(order):
        return _historical_review(reviews.get(order_checks.get(order.id)), order.created_at)

    for order in filled_orders:
        actual = "매수" if order.side == "buy" else "매도"
        comparison = _advice_comparison(order_advice(order), actual)
        if comparison is None or comparison["matched"] is None:
            comparison_counts["excluded"] += 1
        elif comparison["matched"]:
            comparison_counts["matched"] += 1
        else:
            comparison_counts["different"] += 1
            if comparison["advice"] in {"관망", "보류"}:
                comparison_counts["traded_after_wait"] += 1
    compared = comparison_counts["matched"] + comparison_counts["different"]

    deferred_counts = Counter()
    if include_ai:
        for check in deferred:
            advice = _historical_review(reviews.get(check.id), check.decided_at)
            comparison = _advice_comparison(advice, "보류")
            match = comparison["matched"] if comparison else None
            deferred_counts[{True: "matched", False: "different", None: "excluded"}[match]] += 1

    deferred_page = deferred[offset : offset + 50]
    symbols = {order.symbol for order in page} | {c.draft["symbol"] for c in deferred_page}
    names = (
        dict(db.execute(select(Symbol.symbol, Symbol.name).where(Symbol.symbol.in_(symbols))).all())
        if symbols
        else {}
    )
    items = []
    for order in page:
        preflight = order.analysis.get("preflight", {})
        prediction = preflight.get("prediction", {})
        record = records.get(prediction.get("prediction_id"))
        fill = fills.get(order.id)
        items.append(
            dict(
                order_id=order.id,
                symbol=order.symbol,
                symbol_name=names.get(order.symbol),
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
                    source=fill.source,
                    quote_as_of=fill.quote_as_of,
                    realized_pnl_won=None
                    if fill.realized_pnl_won is None
                    else str(fill.realized_pnl_won),
                    created_at=fill.created_at,
                ),
            )
        )
        if include_pretrade:
            items[-1].update(
                pretrade_ai=order_advice(order),
                advice_comparison=_advice_comparison(
                    order_advice(order),
                    ("매수" if order.side == "buy" else "매도") if fill else None,
                ),
                cancelled_at=order.analysis.get("cancelled_at"),
            )
    feedback = [FEEDBACK[code] for code, _ in warnings.most_common(3)]
    if unregistered:
        feedback.append(f"계획 미등록 체결 {unregistered}건은 원칙 준수율 계산에서 제외했습니다.")
    return dict(
        window=dict(start=start, end=at, days=days),
        items=items,
        **(
            {"sample_entries": journal_samples.entries_in_window(start, at)}
            if include_pretrade
            else {}
        ),
        total_orders=len(orders),
        next_offset=offset + 50 if offset + 50 < max(len(orders), len(deferred)) else None,
        deferred_checks=[
            dict(
                check_id=c.id,
                symbol=c.draft["symbol"],
                symbol_name=names.get(c.draft["symbol"]),
                side=c.draft["side"],
                quantity=c.draft["quantity"],
                limit_price_won=str(c.draft["limit_price_won"]),
                decided_at=c.decided_at,
                reason=c.decision_reason,
                pretrade_ai=_historical_review(reviews.get(c.id), c.decided_at),
                advice_comparison=_advice_comparison(
                    _historical_review(reviews.get(c.id), c.decided_at), "보류"
                ),
            )
            for c in deferred_page
        ],
        summary=dict(
            advice_comparison=dict(
                compared=compared,
                matched=comparison_counts["matched"],
                different=comparison_counts["different"],
                traded_after_wait=comparison_counts["traded_after_wait"],
                excluded=comparison_counts["excluded"],
                agreement_rate=comparison_counts["matched"] / compared if compared else None,
                difference_rate=comparison_counts["different"] / compared if compared else None,
            )
            if include_ai
            else None,
            deferred_advice_comparison=dict(deferred_counts) if include_ai else None,
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
