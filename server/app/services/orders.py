from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Holding, Order, OrderCheck, Quote, Symbol, User, now
from ..schemas import CheckResponse, Draft, Receipt, Submit


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
        or not 0 <= (now() - quote.as_of).total_seconds() <= settings.quote_max_age_seconds
    ):
        issues.append("최신 시세를 확인할 수 없습니다.")
    if amount > user.order_limit_won:
        issues.append("1회 주문한도를 초과했습니다.")
    if draft.side == "buy" and amount > user.cash_won - user.reserved_won:
        issues.append("모의투자 주문 가능 잔액이 부족합니다.")
    if draft.side == "sell":
        holding = db.get(Holding, (user.id, draft.symbol))
        if holding is None or draft.quantity > holding.quantity - holding.reserved:
            issues.append("매도 가능한 보유 수량이 부족합니다.")
    return issues


def preflight(db: Session, user_id: str, draft: Draft, settings: Settings) -> CheckResponse:
    user = lock_user(db, user_id)
    if db.get(Symbol, draft.symbol) is None:
        raise HTTPException(404, "등록되지 않은 종목입니다.")
    issues = reasons(db, user, draft, settings)
    messages = list(issues)
    if draft.pilot_enabled:
        messages.append("행동 분석 모듈 미연결: 뇌동매매 판단은 제공하지 않습니다.")
    messages.append("모의주문 접수만 지원합니다. 실제 주문 전송·자동 체결은 없습니다.")
    check = OrderCheck(
        user_id=user.id,
        draft=draft.model_dump(),
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
    )


def submit(db: Session, user_id: str, request: Submit, key: str, settings: Settings) -> Receipt:
    user = lock_user(db, user_id)
    body = request.model_dump()
    previous = db.scalar(
        select(Order).where(Order.user_id == user_id, Order.idempotency_key == key)
    )
    if previous is not None:
        if previous.request_body != body:
            raise HTTPException(409, "같은 주문 식별자에 다른 요청을 사용할 수 없습니다.")
        return receipt(previous)  # BEFORE checking current quote or check expiry.
    if db.get(Symbol, request.symbol) is None:
        raise HTTPException(404, "등록되지 않은 종목입니다.")
    check = db.get(OrderCheck, request.check_id)
    issues = []
    if (
        check is None
        or check.user_id != user_id
        or check.draft != request.draft_dict()
        or check.consumed
        or not check.allowed
        or check.expires_at <= now()
    ):
        issues.append("주문 점검 결과가 유효하지 않습니다. 다시 점검하세요.")
    else:
        issues.extend(reasons(db, user, request, settings))
        check.consumed = True
    if not issues:
        amount = int(request.limit_price_won) * request.quantity
        if request.side == "buy":
            user.reserved_won += amount
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
        status="rejected" if issues else "accepted",
        reason=" ".join(issues) or None,
    )
    db.add(order)
    db.flush()
    return receipt(order)


def cancel(db: Session, user_id: str, order_id: str) -> Receipt:
    user = lock_user(db, user_id)
    order = db.scalar(select(Order).where(Order.id == order_id, Order.user_id == user_id))
    if order is None:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    if order.status == "accepted":
        if order.side == "buy":
            user.reserved_won -= order.quantity * order.limit_price_won
        else:
            holding = db.get(Holding, (user_id, order.symbol))
            holding.reserved -= order.quantity
        order.status = "cancelled"
    return receipt(order)
