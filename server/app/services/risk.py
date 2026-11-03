"""Versioned, explainable rules. Scores are not emotional-state probabilities."""

from datetime import UTC, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from ..models import Candle, Fill, Holding, Order, Quote, QuoteSample, TradePlan, now

VERSION = "behavior-2026-10-20-v2"
POLICY = {
    "price_window_minutes": 10,
    "fomo_percent": 3,
    "panic_percent": -3,
    "loss_streak": 3,
    "revenge_minutes": 30,
    "orders_window_minutes": 60,
    "orders_threshold": 5,
    "caution_score": 30,
    "high_score": 60,
    "weights": {"fomo": 30, "panic": 30, "revenge": 25, "overtrading": 20, "plan": 20},
}
ACCEPTED = ("accepted", "filled", "cancelled")


def plan_context(db, user, draft, quote):
    if not draft.plan_id:
        return None, "unregistered", "계획 미등록", False
    plan = db.get(TradePlan, draft.plan_id)
    if plan is None or plan.user_id != user.id:
        raise HTTPException(404, "매매 계획을 찾을 수 없습니다.")
    if plan.symbol != draft.symbol or plan.side != draft.side:
        return plan, "hit", "선택한 계획의 종목 또는 주문 방향과 다릅니다.", False
    spent = sum(
        o.quantity * o.limit_price_won
        for o in db.scalars(
            select(Order).where(
                Order.user_id == user.id,
                Order.plan_id == plan.id,
                Order.status.in_(("accepted", "filled")),
            )
        )
    )
    amount = draft.quantity * int(draft.limit_price_won)
    if amount + spent > plan.max_amount_won:
        return (
            plan,
            "hit",
            f"계획 금액 한도 {plan.max_amount_won:,}원 초과 (기존 {spent:,}원 포함)",
            False,
        )
    if quote is None:
        return plan, "unavailable", "계획 평가에 필요한 시세가 없습니다.", False
    stop = (
        draft.side == "sell"
        and plan.stop_loss_won is not None
        and quote.price_won <= plan.stop_loss_won
    )
    if stop:
        return plan, "clear", f"저장된 손절가 {plan.stop_loss_won:,}원 이하의 위험 축소 매도", True
    if plan.entry_min_won is None and plan.entry_max_won is None:
        return plan, "unavailable", "가격 범위가 없는 설명형 계획은 자동 판단하지 않습니다.", False
    prices = [quote.price_won, int(draft.limit_price_won)]
    if (plan.entry_min_won is not None and min(prices) < plan.entry_min_won) or (
        plan.entry_max_won is not None and max(prices) > plan.entry_max_won
    ):
        return plan, "hit", "현재가 또는 주문 지정가가 저장된 계획 가격 범위를 벗어납니다.", False
    return plan, "clear", "계획의 종목·방향·가격 범위·누적 금액 조건을 충족합니다.", False


def baseline(db, quote):
    if quote is None:
        return None, None
    target = quote.as_of - timedelta(minutes=10)
    sample = db.scalar(
        select(QuoteSample)
        .where(
            QuoteSample.symbol == quote.symbol,
            QuoteSample.source == quote.source,
            QuoteSample.as_of <= target,
            QuoteSample.as_of >= target - timedelta(seconds=60),
        )
        .order_by(QuoteSample.as_of.desc())
        .limit(1)
    )
    if sample is not None:
        return sample.price_won, sample.as_of
    # Only completed 1m bars whose CLOSE time is at/before the comparison time.
    candle = db.scalar(
        select(Candle)
        .where(
            Candle.symbol == quote.symbol,
            Candle.source == quote.source,
            Candle.interval == "1m",
            Candle.complete.is_(True),
            Candle.opened_at <= target - timedelta(minutes=1),
            Candle.opened_at >= target - timedelta(minutes=2),
        )
        .order_by(Candle.opened_at.desc())
        .limit(1)
    )
    return (candle.close_won, candle.opened_at + timedelta(minutes=1)) if candle else (None, None)


def evaluate(db, user, draft, settings):
    at = now()
    quote = db.get(Quote, draft.symbol)
    fresh = (
        quote is not None
        and 0 <= (at - quote.as_of).total_seconds() <= settings.quote_max_age_seconds
        and (quote.source != "demo" or settings.market_data_mode == "demo")
    )
    quote = quote if fresh else None
    plan, plan_state, plan_message, stop = plan_context(db, user, draft, quote)
    plan_matches = plan_state == "clear"
    base, base_at = baseline(db, quote)
    change = (Decimal(quote.price_won - base) * 100 / Decimal(base)) if base else None
    holding = db.get(Holding, (user.id, draft.symbol))
    position_loss = None
    position_return = None
    if quote and holding and holding.quantity > 0 and holding.cost_won is not None:
        position_loss = quote.price_won * holding.quantity < holding.cost_won
        if holding.cost_won > 0:
            position_return = (
                Decimal(quote.price_won * holding.quantity - holding.cost_won)
                * 100
                / Decimal(holding.cost_won)
            )
    recent_losses = db.scalars(
        select(Fill)
        .where(Fill.user_id == user.id, Fill.side == "sell", Fill.created_at <= at)
        .order_by(Fill.created_at.desc(), Fill.id.desc())
        .limit(3)
    ).all()
    recent_orders = db.scalars(
        select(Order).where(
            Order.user_id == user.id,
            Order.status.in_(ACCEPTED),
            Order.created_at > at - timedelta(minutes=60),
            Order.created_at <= at,
        )
    ).all()
    group = plan.id if plan and plan_matches and plan.split_order else None
    groups = {o.plan_group_id or o.id for o in recent_orders}
    groups.add(group or "current-request")
    count = len(groups)
    # Daily loss is based on the Korean trading day, not the server's local timezone.
    day_start = (
        at.astimezone(ZoneInfo("Asia/Seoul"))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
    )
    daily = db.scalars(
        select(Fill).where(
            Fill.user_id == user.id,
            Fill.side == "sell",
            Fill.created_at >= day_start,
            Fill.created_at <= at,
        )
    ).all()
    known = all(f.realized_pnl_won is not None for f in daily)
    pnl = sum(f.realized_pnl_won or 0 for f in daily)
    last = db.scalar(
        select(Order)
        .where(
            Order.user_id == user.id,
            Order.symbol == draft.symbol,
            Order.side == draft.side,
            Order.status.in_(ACCEPTED),
            Order.created_at <= at,
        )
        .order_by(Order.created_at.desc())
        .limit(1)
    )
    return assess(
        at=at,
        quote=quote,
        draft=draft,
        plan=plan,
        plan_state=plan_state,
        plan_message=plan_message,
        stop=stop,
        base_at=base_at,
        change=change,
        position_loss=position_loss,
        position_return=position_return,
        recent_losses=recent_losses,
        count=count,
        group=group,
        day_start=day_start,
        known=known,
        pnl=pnl,
        last=last,
        user=user,
        settings=settings,
    )


def assess(
    *,
    at,
    quote,
    draft,
    plan,
    plan_state,
    plan_message,
    stop,
    base_at,
    change,
    position_loss,
    position_return,
    recent_losses,
    count,
    group,
    day_start,
    known,
    pnl,
    last,
    user,
    settings,
):
    """Shared policy; callers supply live or isolated replay facts and their clock."""
    plan_matches = plan_state == "clear"
    items = []

    def add(code, title, state, points, message):
        items.append(
            dict(
                code=code,
                title=title,
                status=state,
                points=points if state == "hit" else 0,
                message=message,
            )
        )

    if draft.side != "buy":
        add("fomo", "급등 추격 매수", "not_applicable", 0, "매수 주문에만 적용합니다.")
    elif change is None:
        add(
            "fomo",
            "급등 추격 매수",
            "unavailable",
            0,
            "동일 출처의 10분 전 시세가 부족하거나 현재 시세가 지연되었습니다.",
        )
    elif change >= 3:
        exempt = plan_matches and plan is not None and plan.created_at < base_at
        add(
            "fomo",
            "급등 추격 매수",
            "exempt" if exempt else "hit",
            30,
            f"최근 10분 가격 변화 {change:.2f}% (기준 +3%). "
            + ("급등 이전 계획 조건 충족" if exempt else "가능성 경고; 거래 이유를 확인하세요."),
        )
    else:
        add("fomo", "급등 추격 매수", "clear", 0, f"10분 가격 변화 {change:.2f}%: +3% 미만")
    if draft.side != "sell":
        add("panic", "공포매도", "not_applicable", 0, "매도 주문에만 적용합니다.")
    elif change is None or position_loss is None:
        add(
            "panic",
            "공포매도",
            "unavailable",
            0,
            "10분 전 시세 또는 보유 원가를 확인할 수 없습니다.",
        )
    elif change <= -3 and position_loss:
        exempt = (
            plan_matches
            and plan is not None
            and plan.created_at < base_at
            and (stop or plan.split_order)
        )
        add(
            "panic",
            "공포매도",
            "exempt" if exempt else "hit",
            30,
            f"10분 가격 변화 {change:.2f}% (기준 -3%) · 평가손실 상태. "
            + ("급락 이전 손절/분할청산 계획 충족" if exempt else "계획된 매도인지 재확인하세요."),
        )
    else:
        add("panic", "공포매도", "clear", 0, "급락과 평가손실의 동시 조건에 해당하지 않습니다.")
    if draft.side != "buy":
        add("revenge", "복수매매", "not_applicable", 0, "보유량 축소 매도는 제외합니다.")
    elif any(f.realized_pnl_won is None for f in recent_losses):
        add(
            "revenge",
            "복수매매",
            "unavailable",
            0,
            "최근 청산 원가 또는 실현손익을 확인할 수 없습니다.",
        )
    elif (
        len(recent_losses) == 3
        and all(f.realized_pnl_won < 0 for f in recent_losses)
        and at - recent_losses[0].created_at <= timedelta(minutes=30)
    ):
        exempt = (
            plan_matches
            and plan is not None
            and plan.split_order
            and plan.created_at < recent_losses[-1].created_at
        )
        add(
            "revenge",
            "복수매매",
            "exempt" if exempt else "hit",
            25,
            "최근 청산 3건 연속 순손실 · 마지막 손실 후 30분 이내 매수. "
            + (
                "손실 이전 분할매수 계획 충족"
                if exempt
                else "손실 만회 목적의 반복 매수 가능성을 확인하세요."
            ),
        )
    else:
        add(
            "revenge",
            "복수매매",
            "clear",
            0,
            "3건 연속 손실·30분 이내 매수 조건에 해당하지 않습니다.",
        )
    add(
        "overtrading",
        "과매매",
        "hit" if count >= 5 else "clear",
        20,
        f"현재 주문 포함 최근 60분 접수 {count}건 (기준 5건). "
        "검증된 분할 계획은 1건으로 집계합니다.",
    )
    add("plan", "매매 계획 위반", plan_state, 20, plan_message)
    score = min(100, sum(i["points"] for i in items))
    partial = any(i["status"] == "unavailable" for i in items)
    behavior = dict(
        enabled=draft.pilot_enabled,
        score=score,
        level="high" if score >= 60 else "caution" if score >= 30 else "low",
        partial=partial,
        items=items,
        change_10m_percent=None if change is None else str(change.quantize(Decimal("0.01"))),
        baseline_as_of=base_at.isoformat() if base_at else None,
        quote_as_of=quote.as_of.isoformat() if quote else None,
        source=quote.source if quote else None,
        requires_ack=score >= 30,
        requires_high_ack=score >= 60,
    )
    if not draft.pilot_enabled:
        behavior.update(
            score=0,
            level="disabled",
            items=[],
            partial=False,
            requires_ack=False,
            requires_high_ack=False,
        )

    issues = []
    if settings.orders_halted or user.trading_paused:
        issues.append("신규 모의주문이 정지되어 있습니다. 기존 주문 취소는 가능합니다.")
    if draft.side == "buy":
        if not known:
            issues.append("당일 실현손익을 확인할 수 없어 신규·추가 매수를 차단합니다.")
        elif pnl <= -user.daily_loss_limit_won:
            issues.append(
                f"일일 손실한도 도달: 순실현손익 {pnl:,}원 / 한도 {user.daily_loss_limit_won:,}원. "
                "매도는 허용됩니다."
            )
    remaining = 0
    if last and user.cooldown_seconds > 0:
        remaining = max(0, user.cooldown_seconds - int((at - last.created_at).total_seconds()))
        exempt = (
            draft.side == "sell" and stop and plan_matches and plan.created_at < last.created_at
        )
        if remaining and not exempt:
            issues.append(f"동일 종목·방향 주문 쿨다운: 약 {remaining}초 후 다시 점검하세요.")
    return dict(
        version=VERSION,
        policy=POLICY,
        context=dict(
            position_return_percent=None
            if position_return is None
            else str(position_return.quantize(Decimal("0.01"))),
            stop_loss_won=plan.stop_loss_won if plan else None,
            plan_status=plan_state,
            plan_message=plan_message,
        ),
        evaluated_at=at.isoformat(),
        behavior=behavior,
        risk=dict(
            reasons=issues,
            daily_pnl_won=str(pnl) if known else None,
            day_start=day_start.isoformat(),
            cooldown_remaining_seconds=remaining,
            trading_paused=user.trading_paused or settings.orders_halted,
        ),
        plan_id=draft.plan_id,
        plan_group_id=group,
        plan=None
        if plan is None
        else dict(
            id=plan.id,
            created_at=plan.created_at.isoformat(),
            status=plan_state,
            entry_min_won=plan.entry_min_won,
            entry_max_won=plan.entry_max_won,
            stop_loss_won=plan.stop_loss_won,
            max_amount_won=plan.max_amount_won,
            split_order=plan.split_order,
            entry_condition=plan.entry_condition,
        ),
    )


def messages(analysis):
    behavior = analysis["behavior"]
    if not behavior["enabled"]:
        return ["행동 경고 OFF · 주문한도·손실한도·쿨다운·거래 정지는 계속 적용됩니다."]
    level = {"low": "낮음", "caution": "주의", "high": "높음"}[behavior["level"]]
    result = [
        f"행동 점수 {behavior['score']}/100 · {level}"
        + (" · 일부 판단 불가" if behavior["partial"] else ""),
        "점수는 감정적 거래일 확률이 아닌 규칙 기반 경고입니다.",
    ]
    for item in behavior["items"]:
        if item["status"] != "not_applicable":
            result.append(f"{item['title']} (+{item['points']}): {item['message']}")
    return result
