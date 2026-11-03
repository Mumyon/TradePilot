from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Holding, Order, OrderCheck, Quote, Symbol, User, now
from ..schemas import CheckResponse, Draft, Receipt, Submit
from . import predictions, risk
from .fees import reserve


def receipt(order: Order) -> Receipt:
    return Receipt(order_id=order.id, symbol=order.symbol, status=order.status, reason=order.reason)


def lock_user(db: Session, user_id: str) -> User:
    # Every paper balance/holding mutation must take this lock first.
    user = db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None or not user.enabled:
        raise HTTPException(401, "계정이 비활성화되었습니다.")
    return user


def reasons(db: Session, user: User, draft: Draft, settings: Settings) -> list[str]:
    issues = []
    price = int(draft.limit_price_won)
    amount = price * draft.quantity
    quote = db.get(Quote, draft.symbol)
    if (
        quote is None
        or (quote.source == "demo" and settings.market_data_mode != "demo")
        or not 0 <= (now() - quote.as_of).total_seconds() <= settings.quote_max_age_seconds
    ):
        issues.append("최신 시세를 확인할 수 없습니다.")
    if amount > user.order_limit_won:
        issues.append("1회 주문한도를 초과했습니다.")
    if draft.side == "buy" and reserve(amount) > user.cash_won - user.reserved_won:
        issues.append("모의투자 주문 가능 잔액이 부족합니다.")
    if draft.side == "sell":
        holding = db.get(Holding, (user.id, draft.symbol))
        if holding is None or draft.quantity > holding.quantity - holding.reserved:
            issues.append("매도 가능한 보유 수량이 부족합니다.")
    return issues


def preflight(
    db: Session, user_id: str, draft: Draft, settings: Settings, *, origin="manual"
) -> CheckResponse:
    user = lock_user(db, user_id)
    if db.get(Symbol, draft.symbol) is None:
        raise HTTPException(404, "등록되지 않은 종목입니다.")
    analysis = risk.evaluate(db, user, draft, settings)
    analysis["prediction"] = predictions.get_prediction(db, draft.symbol, settings)
    issues = reasons(db, user, draft, settings) + analysis["risk"]["reasons"]
    messages = list(issues) + risk.messages(analysis)
    messages.append(
        "모의주문입니다. 접수 후 새 시세가 지정가 조건을 충족하면 전량 모의 체결됩니다. "
        "수수료는 편도 0.015%입니다."
    )
    check = OrderCheck(
        user_id=user.id,
        origin=origin,
        draft=draft.model_dump(),
        analysis=analysis,
        allowed=not issues,
        messages=messages,
        expires_at=now() + timedelta(seconds=settings.order_check_ttl_seconds),
    )
    db.add(check)
    db.flush()
    return CheckResponse(
        check_id=check.id,
        allowed=check.allowed,
        messages=check.messages,
        expires_at=check.expires_at,
        analysis=check.analysis,
    )


def submit(db: Session, user_id: str, request: Submit, key: str, settings: Settings) -> Receipt:
    user = lock_user(db, user_id)
    body = request.model_dump()
    previous = db.scalar(
        select(Order).where(Order.user_id == user_id, Order.idempotency_key == key)
    )
    if previous is not None:
        if Submit.model_validate(previous.request_body).model_dump() != body:
            raise HTTPException(409, "같은 주문 식별자에 다른 요청을 사용할 수 없습니다.")
        return receipt(previous)  # BEFORE checking current quote or check expiry.
    if db.get(Symbol, request.symbol) is None:
        raise HTTPException(404, "등록되지 않은 종목입니다.")
    check = db.get(OrderCheck, request.check_id)
    issues = []
    assessment = None
    if (
        check is None
        or check.user_id != user_id
        or Draft.model_validate(check.draft).model_dump() != request.draft_dict()
        or check.consumed
        or not check.allowed
        or check.expires_at <= now()
    ):
        issues.append("주문 점검 결과가 유효하지 않습니다. 다시 점검하세요.")
    else:
        assessment = risk.evaluate(db, user, request, settings)
        issues.extend(reasons(db, user, request, settings))
        issues.extend(assessment["risk"]["reasons"])
        original = check.analysis.get("behavior", {})
        current = assessment["behavior"]
        original_hits = {i["code"] for i in original.get("items", []) if i["status"] == "hit"}
        current_hits = {i["code"] for i in current["items"] if i["status"] == "hit"}
        if current["enabled"] and (
            current_hits - original_hits or current["score"] > original.get("score", 0)
        ):
            issues.append("점검 이후 새로운 행동 경고가 발생했습니다. 다시 점검하세요.")
        needs_ack = original.get("requires_ack", False) or current["requires_ack"]
        needs_high = original.get("requires_high_ack", False) or current["requires_high_ack"]
        if needs_ack and (
            not request.warning_acknowledged or len(request.trade_reason.strip()) < 3
        ):
            issues.append("행동 경고 확인과 3자 이상의 거래 이유가 필요합니다.")
        if needs_high and not request.high_risk_acknowledged:
            issues.append("높음 단계: 계획과 주문 내용의 추가 확인이 필요합니다.")
        check.consumed = True
        check.decision = "submitted"
        check.decided_at = now()
    if not issues:
        amount = int(request.limit_price_won) * request.quantity
        if request.side == "buy":
            user.reserved_won += reserve(amount)
        else:
            holding = db.get(Holding, (user_id, request.symbol))
            holding.reserved += request.quantity
    order = Order(
        user_id=user_id,
        idempotency_key=key,
        request_body=body,
        symbol=request.symbol,
        side=request.side,
        quantity=request.quantity,
        limit_price_won=int(request.limit_price_won),
        reserved_cash_won=reserve(int(request.limit_price_won) * request.quantity)
        if not issues and request.side == "buy"
        else 0,
        plan_id=request.plan_id if assessment is not None else None,
        plan_group_id=assessment["plan_group_id"]
        if assessment is not None and not issues
        else None,
        analysis={
            "preflight": check.analysis if check and check.user_id == user_id else {},
            "submission": assessment,
            "trade_reason": request.trade_reason,
            "warning_acknowledged": request.warning_acknowledged,
            "high_risk_acknowledged": request.high_risk_acknowledged,
            "blocking_reasons": issues,
        },
        status="rejected" if issues else "accepted",
        reason=" ".join(issues)[:500] or None,
    )
    db.add(order)
    db.flush()
    if assessment is not None:
        check.submitted_order_id = order.id
    return receipt(order)


def cancel(db: Session, user_id: str, order_id: str) -> Receipt:
    user = lock_user(db, user_id)
    order = db.scalar(select(Order).where(Order.id == order_id, Order.user_id == user_id))
    if order is None:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    if order.status == "accepted":
        if order.side == "buy":
            user.reserved_won -= order.reserved_cash_won
        else:
            holding = db.get(Holding, (user_id, order.symbol))
            holding.reserved -= order.quantity
        order.status = "cancelled"
    return receipt(order)
