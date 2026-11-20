from datetime import datetime, time
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Date, cast, func, select

from ..brokers.contracts import accepts_source
from ..models import Fill, Holding, Order, Quote, Symbol, now
from . import market_hours
from .fees import fee
from .orders import cancel, lock_user


def settle(db, user_id, settings, *, test_order_id=None, test_quote=None):
    user = lock_user(db, user_id)
    query = select(Order).where(Order.user_id == user_id, Order.status == "accepted")
    if test_order_id is not None:
        query = query.where(Order.id == test_order_id)
    pending = db.scalars(query.order_by(Order.created_at, Order.id)).all()
    for order in pending:
        if order.analysis.get("test_mode"):
            if test_order_id != order.id or test_quote is None:
                continue
            quote = test_quote
        else:
            if market_hours.expired(db, settings, order.created_at):
                cancel(db, user_id, order.id)
                order.reason = "당일 정규장 종료로 미체결 모의주문이 자동 취소되었습니다."
                continue
            quote = db.get(Quote, order.symbol)
            if (
                quote is None
                or quote.as_of <= order.created_at
                or not 0 <= (now() - quote.as_of).total_seconds() <= settings.quote_max_age_seconds
                or not accepts_source(quote.source, settings)
            ):
                order.reason = "최신 실제 체결 시세를 기다리는 중입니다."
                continue
            allowed, message = market_hours.execution_allowed(db, settings, quote.as_of)
            if not allowed:
                order.reason = message
                continue
        buy = order.side == "buy"
        if (buy and quote.price_won > order.limit_price_won) or (
            not buy and quote.price_won < order.limit_price_won
        ):
            order.reason = "지정가 조건을 충족하는 실제 체결 시세를 기다리는 중입니다."
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
        order.reason = None
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
                source="test_mode" if test_order_id is not None else quote.source,
                quote_as_of=quote.as_of,
            )
        )
        db.flush()


def _return_percent(pnl, basis):
    if pnl is None or basis is None or basis <= 0:
        return None
    percent = (Decimal(pnl) * 100 / basis).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return str(abs(percent) if percent == 0 else percent)


def account(db, user_id, settings, provider=None):
    user = lock_user(db, user_id)
    holdings = []
    total = user.cash_won
    complete = True
    valuation = cost = estimated_sell_fees = 0
    prices_complete = costs_complete = True
    stale_valuation = False
    at = now()
    for holding, name in db.execute(
        select(Holding, Symbol.name)
        .join(Symbol)
        .where(Holding.user_id == user_id, Holding.quantity > 0)
    ).all():
        quote = db.get(Quote, holding.symbol)
        if quote and (quote.as_of > at or not accepts_source(quote.source, settings)):
            quote = None
        fresh = (
            quote is not None
            and (at - quote.as_of).total_seconds() <= settings.quote_max_age_seconds
        )
        value = holding.quantity * quote.price_won if fresh else None
        # Cached display quotes can value holdings without becoming executable ticks.
        display_quote = quote
        if provider is not None:
            try:
                cached = provider.get_quote(holding.symbol)
            except RuntimeError:
                cached = None
            if (
                cached is not None
                and cached.price_won > 0
                and cached.as_of <= at
                and accepts_source(cached.source, settings)
                and (quote is None or cached.as_of > quote.as_of)
            ):
                display_quote = cached
        priced = display_quote is not None
        display_stale = (
            not priced
            or (at - display_quote.as_of).total_seconds() > settings.quote_max_age_seconds
        )
        last_value = holding.quantity * display_quote.price_won if priced else None
        basis = holding.cost_won
        sell_fee = fee(last_value) if last_value is not None else None
        valuation_pnl = (
            last_value - sell_fee - basis if sell_fee is not None and basis is not None else None
        )
        prices_complete &= priced
        costs_complete &= holding.cost_won is not None
        stale_valuation |= priced and display_stale
        valuation += last_value or 0
        cost += holding.cost_won or 0
        estimated_sell_fees += sell_fee or 0
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
                price_won=str(display_quote.price_won) if priced else None,
                valuation_won=None if last_value is None else str(last_value),
                valuation_pnl_won=None if valuation_pnl is None else str(valuation_pnl),
                valuation_return_percent=_return_percent(valuation_pnl, basis),
                quote_as_of=display_quote.as_of if priced else None,
                stale=display_stale,
            )
        )
    realized, known, sells = db.execute(
        select(
            func.sum(Fill.realized_pnl_won), func.count(Fill.realized_pnl_won), func.count()
        ).where(Fill.user_id == user_id, Fill.side == "sell")
    ).one()
    valuation_pnl = (
        valuation - cost - estimated_sell_fees if prices_complete and costs_complete else None
    )
    return dict(
        mode="paper",
        market_session=market_hours.status(db, settings),
        cash_won=str(user.cash_won),
        reserved_won=str(user.reserved_won),
        available_cash_won=str(user.cash_won - user.reserved_won),
        equity_won=str(total) if complete else None,
        realized_pnl_won=str(realized or 0),
        realized_pnl_complete=known == sells,
        holdings=holdings,
        stock_balance=dict(
            cost_won=str(cost) if costs_complete else None,
            market_value_won=str(valuation) if prices_complete else None,
            unrealized_pnl_won=None if valuation_pnl is None else str(valuation_pnl),
            return_percent=_return_percent(valuation_pnl, cost),
            equity_won=str(user.cash_won + valuation) if prices_complete else None,
            stale=stale_valuation,
        ),
        as_of=at,
        fee_policy="모의 수수료 편도 0.015% 원 단위 올림 · 세금/슬리피지 미반영",
    )


def trade_profit(db, user_id, group_by, start_date, end_date, symbol):
    realized_sales = (
        Fill.user_id == user_id,
        Fill.side == "sell",
        Fill.realized_pnl_won.is_not(None),
    )
    day = cast(func.timezone("Asia/Seoul", Fill.created_at), Date)
    amount = Fill.price_won * Fill.quantity
    # Settlement records net P/L. Subtracting it from net proceeds recovers
    # the exact fee-inclusive cost allocated to the sold shares, even on old fills.
    basis = amount - Fill.fee_won - Fill.realized_pnl_won
    filters = list(realized_sales)
    if start_date is not None:
        filters.append(Fill.created_at >= datetime.combine(start_date, time.min, market_hours.KST))
    if end_date is not None:
        end = datetime.combine(end_date, time.max, market_hours.KST)
        filters.append(Fill.created_at <= end)
    if symbol is not None:
        filters.append(Fill.symbol == symbol)

    amounts = dict(
        sell_amount_won=func.sum(amount),
        sell_quantity=func.sum(Fill.quantity),
        fees_won=func.sum(Fill.fee_won),
        realized_pnl_won=func.sum(Fill.realized_pnl_won),
        sell_cost_won=func.sum(basis),
    )
    instrument = [Fill.symbol, Symbol.name] if group_by == "symbol" else []
    rows = db.execute(
        select(
            *instrument,
            func.min(day).label("start_date"),
            func.max(day).label("end_date"),
            *(expr.label(key) for key, expr in amounts.items()),
        )
        .select_from(Fill)
        .join(Symbol)
        .where(*filters)
        .group_by(*(instrument or [day]))
        .order_by(func.max(day).desc(), *instrument)
    ).all()

    def display(values):
        result = {
            key: int(values[key] or 0) if key == "sell_quantity" else str(values[key] or 0)
            for key in amounts
        }
        result["realized_return_percent"] = _return_percent(
            values["realized_pnl_won"], values["sell_cost_won"]
        )
        return result

    traded_symbols = db.execute(
        select(Symbol.symbol, Symbol.name)
        .where(select(Fill.id).where(*realized_sales, Fill.symbol == Symbol.symbol).exists())
        .order_by(Symbol.name, Symbol.symbol)
    ).all()
    return {
        "symbols": [dict(symbol=code, name=name) for code, name in traded_symbols],
        "summary": display({key: sum(row._mapping[key] for row in rows) for key in amounts}),
        "items": [
            {
                "start_date": row.start_date,
                "end_date": row.end_date,
                **({"symbol": row.symbol, "name": row.name} if group_by == "symbol" else {}),
                **display(row._mapping),
            }
            for row in rows
        ],
    }
