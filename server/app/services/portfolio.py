from sqlalchemy import select

from ..models import Fill, Holding, Order, Quote, Symbol, now
from .fees import fee
from .orders import lock_user


def settle(db, user_id, settings):
    user = lock_user(db, user_id)
    pending = db.scalars(
        select(Order)
        .where(Order.user_id == user_id, Order.status == "accepted")
        .order_by(Order.created_at, Order.id)
    ).all()
    for order in pending:
        quote = db.get(Quote, order.symbol)
        if (
            quote is None
            or quote.as_of <= order.created_at
            or not 0 <= (now() - quote.as_of).total_seconds() <= settings.quote_max_age_seconds
            or (quote.source == "demo" and settings.market_data_mode != "demo")
        ):
            continue
        buy = order.side == "buy"
        if (buy and quote.price_won > order.limit_price_won) or (
            not buy and quote.price_won < order.limit_price_won
        ):
            continue
        holding = db.get(Holding, (user_id, order.symbol))
        if holding is None:
            holding = Holding(
                user_id=user_id, symbol=order.symbol, quantity=0, reserved=0, cost_won=0
            )
            db.add(holding)
        amount = quote.price_won * order.quantity
        charge = fee(amount)
        pnl = None
        if buy:
            if amount + charge > order.reserved_cash_won + user.cash_won - user.reserved_won:
                order.reason = "모의 체결 수수료를 포함한 잔액 부족: 취소 후 다시 주문하세요."
                continue
            user.reserved_won -= order.reserved_cash_won
            user.cash_won -= amount + charge
            if holding.quantity == 0:
                holding.cost_won = 0
            if holding.cost_won is not None:
                holding.cost_won += amount + charge
            holding.quantity += order.quantity
        else:
            if holding.cost_won is not None:
                basis = holding.cost_won * order.quantity // holding.quantity
                pnl = amount - charge - basis
                holding.cost_won -= basis
            holding.reserved -= order.quantity
            holding.quantity -= order.quantity
            user.cash_won += amount - charge
        order.status = "filled"
        db.add(
            Fill(
                order_id=order.id,
                user_id=user_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price_won=quote.price_won,
                fee_won=charge,
                realized_pnl_won=pnl,
                source=quote.source,
                quote_as_of=quote.as_of,
            )
        )
        db.flush()


def account(db, user_id, settings):
    user = lock_user(db, user_id)
    holdings = []
    total = user.cash_won
    complete = True
    for holding, name in db.execute(
        select(Holding, Symbol.name)
        .join(Symbol)
        .where(Holding.user_id == user_id, Holding.quantity > 0)
    ).all():
        quote = db.get(Quote, holding.symbol)
        fresh = (
            quote is not None
            and 0 <= (now() - quote.as_of).total_seconds() <= settings.quote_max_age_seconds
            and (quote.source != "demo" or settings.market_data_mode == "demo")
        )
        value = holding.quantity * quote.price_won if fresh else None
        complete = complete and fresh
        if value is not None:
            total += value
        holdings.append(
            dict(
                symbol=holding.symbol,
                name=name,
                quantity=holding.quantity,
                available_quantity=holding.quantity - holding.reserved,
                cost_won=None if holding.cost_won is None else str(holding.cost_won),
                average_price_won=None
                if holding.cost_won is None
                else str(holding.cost_won // holding.quantity),
                market_value_won=None if value is None else str(value),
                unrealized_pnl_won=None
                if value is None or holding.cost_won is None
                else str(value - holding.cost_won),
                quote_as_of=quote.as_of if quote else None,
                stale=not fresh,
            )
        )
    fills = db.scalars(select(Fill).where(Fill.user_id == user_id, Fill.side == "sell")).all()
    known = [f.realized_pnl_won for f in fills if f.realized_pnl_won is not None]
    return dict(
        mode="paper",
        cash_won=str(user.cash_won),
        reserved_won=str(user.reserved_won),
        available_cash_won=str(user.cash_won - user.reserved_won),
        equity_won=str(total) if complete else None,
        realized_pnl_won=str(sum(known)),
        realized_pnl_complete=len(known) == len(fills),
        holdings=holdings,
        as_of=now(),
        fee_policy="모의 수수료 편도 0.015% 원 단위 올림 · 세금/슬리피지 미반영",
    )
