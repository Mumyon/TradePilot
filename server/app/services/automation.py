"""Opt-in demo-only execution. Uses the existing paper order risk/settlement path."""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from ..models import Automation, AutomationEvent, Candle, Holding, Order, Quote, Strategy, now
from ..schemas import Draft, Submit
from . import backtests, candles, orders


def serialize(item):
    return dict(
        id=item.id,
        strategy_id=item.strategy_id,
        symbol=item.symbol,
        strategy_snapshot=item.snapshot,
        budget_won=item.budget_won,
        enabled=item.enabled,
        last_bar=item.last_bar,
        message=item.message,
        created_at=item.created_at,
        mode="synthetic_paper",
    )


def own_orders(db, item):
    return db.scalars(
        select(Order)
        .join(AutomationEvent, AutomationEvent.order_id == Order.id)
        .where(AutomationEvent.automation_id == item.id)
    ).all()


def manual_intervention(db, item):
    return (
        db.scalar(
            select(Order.id)
            .where(
                Order.user_id == item.user_id,
                Order.symbol == item.symbol,
                Order.created_at >= item.created_at,
                Order.status.in_(["accepted", "filled", "cancelled"]),
                ~Order.id.in_(
                    select(AutomationEvent.order_id).where(
                        AutomationEvent.order_id.is_not(None),
                        AutomationEvent.automation_id == item.id,
                    )
                ),
            )
            .limit(1)
        )
        is not None
    )


def stop(db, item, message):
    # Lock order: always user first. Cancelling preserves filled positions.
    for order in own_orders(db, item):
        if order.status == "accepted":
            orders.cancel(db, item.user_id, order.id)
    item.enabled = False
    item.message = message


def configure(db, user_id, strategy_id, body, settings):
    user = orders.lock_user(db, user_id)
    strategy = backtests.owned(db, user_id, strategy_id)
    item = db.scalar(select(Automation).where(Automation.strategy_id == strategy_id))
    if not body.enabled:
        if item is None:
            raise HTTPException(404, "시작된 자동매매가 없습니다.")
        stop(db, item, "중지됨 · 미체결 자동 주문 취소, 보유 주식 유지")
        return serialize(item)
    if settings.market_data_mode != "demo" or not settings.paper_worker_enabled:
        raise HTTPException(409, "모의 워커가 실행 중인 합성 시연 서버에서만 지원합니다.")
    if settings.orders_halted or user.trading_paused:
        raise HTTPException(409, "거래 정지 설정을 먼저 확인하세요.")
    if not strategy.config["enabled"]:
        raise HTTPException(409, "비활성 전략입니다.")
    if body.budget_won > user.order_limit_won:
        raise HTTPException(422, "예산이 계좌의 1회 주문한도를 초과합니다.")
    others = db.scalars(
        select(Automation).where(
            Automation.user_id == user_id,
            Automation.symbol == strategy.config["symbol"],
            Automation.strategy_id != strategy_id,
        )
    ).all()
    if any(a.enabled or any(o.status == "accepted" for o in own_orders(db, a)) for a in others):
        raise HTTPException(409, "같은 종목에 실행 중인 자동매매가 있습니다.")
    if item is None:
        holding = db.get(Holding, (user_id, strategy.config["symbol"]))
        pending = db.scalar(
            select(Order.id)
            .where(
                Order.user_id == user_id,
                Order.symbol == strategy.config["symbol"],
                Order.status == "accepted",
            )
            .limit(1)
        )
        if (holding and holding.quantity > 0) or pending:
            raise HTTPException(
                409, "첫 시작은 해당 종목의 보유 주식과 미체결 주문이 없어야 합니다."
            )
        item = Automation(
            user_id=user_id,
            strategy_id=strategy_id,
            symbol=strategy.config["symbol"],
            snapshot=dict(strategy.config),
            budget_won=body.budget_won,
        )
        db.add(item)
        db.flush()
    else:
        if manual_intervention(db, item):
            raise HTTPException(
                409, "수동 거래가 개입된 실행입니다. 보유/미체결 정리 후 새 전략을 저장하세요."
            )
        if item.snapshot != strategy.config or item.budget_won != body.budget_won:
            raise HTTPException(
                409, "실행 설정은 고정됩니다. 변경하려면 중지·보유 정리 후 새 전략을 만드세요."
            )
    item.enabled = True
    item.message = "합성 시세 모의 자동매매 · 최근 완료 5분봉 신호 평가 대기"
    return serialize(item)


def process(db, automation_id, provider, settings):
    item = db.get(Automation, automation_id)
    if item is None:
        return
    user = orders.lock_user(db, item.user_id)
    db.refresh(item)  # Re-read after user lock to serialize stop and multiple workers.
    if not item.enabled:
        return
    if settings.market_data_mode != "demo" or settings.orders_halted or user.trading_paused:
        stop(db, item, "거래 정지/서버 설정으로 자동 중지 · 미체결 취소")
        return
    strategy = db.get(Strategy, item.strategy_id)
    if not strategy.config["enabled"]:
        stop(db, item, "전략 비활성화로 자동 중지 · 미체결 취소")
        return
    if manual_intervention(db, item):
        stop(db, item, "같은 종목 수동 거래 감지 · 자동 중지 및 미체결 취소")
        return
    candles.ingest(db, item.symbol, "5m", provider.get_candles(item.symbol, "5m"))
    rows = list(
        reversed(
            db.scalars(
                select(Candle)
                .where(
                    Candle.symbol == item.symbol,
                    Candle.source == "demo",
                    Candle.interval == "5m",
                    Candle.complete.is_(True),
                    Candle.opened_at <= now() - timedelta(minutes=5),
                )
                .order_by(Candle.opened_at.desc())
                .limit(item.snapshot["slow_period"])
            ).all()
        )
    )
    if not rows or now() - rows[-1].opened_at >= timedelta(minutes=10):
        item.message = "최신 완료 5분봉 대기"
        return
    latest = rows[-1].opened_at
    if item.last_bar is not None and latest <= item.last_bar:
        return
    item.last_bar = latest
    event = AutomationEvent(automation_id=item.id, bar_at=latest, signal="wait", message="")
    db.add(event)
    if len(rows) < item.snapshot["slow_period"] or any(
        b.opened_at - a.opened_at != timedelta(minutes=5) for a, b in zip(rows, rows[1:])
    ):
        event.message = item.message = "연속된 5분봉 부족 · 주문 건너뜀"
        return
    fast = item.snapshot["fast_period"]
    buy = sum(r.close_won for r in rows[-fast:]) * len(rows) > sum(r.close_won for r in rows) * fast
    event.signal = "buy" if buy else "sell"
    prior = own_orders(db, item)
    if any(o.status == "accepted" for o in prior):
        event.message = item.message = "이전 자동 주문 미체결 · 신규 주문 건너뜀"
        return
    owned = sum(o.quantity * (1 if o.side == "buy" else -1) for o in prior if o.status == "filled")
    if (buy and owned > 0) or (not buy and owned <= 0):
        event.message = item.message = "현재 보유 상태 유지 · 추가 주문 없음"
        return
    quote = db.get(Quote, item.symbol)
    if (
        quote is None
        or quote.source != "demo"
        or not 0 <= (now() - quote.as_of).total_seconds() <= settings.quote_max_age_seconds
    ):
        event.message = item.message = "최신 합성 시세 없음 · 주문 건너뜀"
        return
    # Budget includes the same 0.015% fee used by paper reservation/settlement.
    qty = min(1_000_000, item.budget_won * 100000 // (quote.price_won * 100015)) if buy else owned
    if qty <= 0:
        event.message = item.message = "예산으로 1주를 살 수 없어 주문 건너뜀"
        return
    draft = Draft(
        symbol=item.symbol,
        side=event.signal,
        quantity=qty,
        limit_price_won=str(quote.price_won),
        pilot_enabled=True,
    )
    check = orders.preflight(db, item.user_id, draft, settings, origin="automation")
    if not check.allowed or check.analysis["behavior"]["requires_ack"]:
        from ..models import OrderCheck

        stored = db.get(OrderCheck, check.check_id)
        stored.decision = "dismissed"
        stored.consumed = True
        reason = " / ".join(check.messages[:-1])
        event.message = item.message = ("위험/행동 점검으로 건너뜀: " + reason)[:1000]
        return
    receipt = orders.submit(
        db,
        item.user_id,
        Submit(
            **draft.model_dump(),
            check_id=check.check_id,
            trade_reason="모의 자동매매: 저장된 이동평균 전략 신호",
        ),
        f"auto:{item.id}:{latest.isoformat()}",
        settings,
    )
    event.order_id = receipt.order_id
    event.message = item.message = (
        f"모의 {event.signal} {qty}주 · {receipt.status} " + (receipt.reason or "")
    )[:1000]
    db.flush()
