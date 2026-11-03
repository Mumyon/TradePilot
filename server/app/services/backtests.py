"""Long-only SMA simulation. Signals at close; fills at the next contiguous open.

No account, holding, order or broker writes are performed here.
"""

import hashlib
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from ..models import Backtest, Candle, Strategy, now
from . import datasets


def owned(db, user_id, strategy_id):
    strategy = db.get(Strategy, strategy_id)
    if strategy is None or strategy.user_id != user_id:
        raise HTTPException(404, "전략을 찾을 수 없습니다.")
    return strategy


def simulate(rows, config, request):
    fast, slow = config["fast_period"], config["slow_period"]
    cash = initial = request.initial_cash_won
    quantity = cost = fees = peak_loss = 0
    peak = initial
    closes, trades, curve, profits = [], [], [], []
    desired = None
    prior = None
    for row in rows:
        stamp = row["opened_at"]
        # A gap invalidates a signal and resets indicators; positions remain held.
        contiguous = prior is not None and stamp - prior == timedelta(minutes=5)
        if not contiguous:
            closes = []
        if contiguous and desired and quantity == 0:
            price = (row["open_won"] * (10000 + request.slippage_bps) + 9999) // 10000
            qty = cash * 10000 // (price * (10000 + request.fee_bps))
            fee = (qty * price * request.fee_bps + 9999) // 10000
            if qty > 0:
                cost = qty * price + fee
                cash -= cost
                quantity = qty
                fees += fee
                trades.append(
                    dict(
                        side="buy",
                        at=stamp.isoformat(),
                        price_won=price,
                        quantity=qty,
                        fee_won=fee,
                        realized_pnl_won=None,
                    )
                )
        elif contiguous and desired is False and quantity > 0:
            price = row["open_won"] * (10000 - request.slippage_bps) // 10000
            fee = (quantity * price * request.fee_bps + 9999) // 10000
            proceeds = quantity * price - fee
            pnl = proceeds - cost
            cash += proceeds
            fees += fee
            profits.append(pnl)
            trades.append(
                dict(
                    side="sell",
                    at=stamp.isoformat(),
                    price_won=price,
                    quantity=quantity,
                    fee_won=fee,
                    realized_pnl_won=pnl,
                )
            )
            quantity = cost = 0
        equity = cash + quantity * row["close_won"]
        peak = max(peak, equity)
        peak_loss = max(peak_loss, (peak - equity) / peak * 100)
        curve.append(dict(at=(stamp + timedelta(minutes=5)).isoformat(), equity_won=equity))
        closes.append(row["close_won"])
        closes = closes[-slow:]
        desired = (sum(closes[-fast:]) * slow > sum(closes) * fast) if len(closes) == slow else None
        prior = stamp
    wins, losses = [p for p in profits if p > 0], [p for p in profits if p < 0]
    final = curve[-1]["equity_won"]
    serial = [{**r, "opened_at": r["opened_at"].isoformat()} for r in rows]
    return dict(
        engine_version="sma-next-open-v1",
        strategy_snapshot=config.copy(),
        parameters=request.model_dump(mode="json"),
        data_label="합성 시연 데이터"
        if request.source == "demo"
        else "CSV 입력 데이터 (출처 확인 필요)",
        dataset_sha256=hashlib.sha256(json.dumps(serial, sort_keys=True).encode()).hexdigest(),
        bar_count=len(rows),
        first_bar=serial[0]["opened_at"],
        last_bar=serial[-1]["opened_at"],
        initial_cash_won=initial,
        final_equity_won=final,
        cash_won=cash,
        open_quantity=quantity,
        unrealized_pnl_won=quantity * rows[-1]["close_won"] - cost,
        realized_pnl_won=sum(profits),
        fee_won=fees,
        return_pct=(final / initial - 1) * 100,
        max_drawdown_pct=peak_loss,
        round_trips=len(profits),
        wins=len(wins),
        losses=len(losses),
        flat=len(profits) - len(wins) - len(losses),
        win_rate_pct=len(wins) / len(profits) * 100 if profits else None,
        average_win_won=sum(wins) / len(wins) if wins else None,
        average_loss_won=sum(losses) / len(losses) if losses else None,
        end_policy="마지막 종가 평가, 강제 청산 없음",
        trades=trades,
        equity_curve=curve,
    )


def run(db, user_id, strategy_id, request):
    strategy = owned(db, user_id, strategy_id)
    if not strategy.config["enabled"]:
        raise HTTPException(409, "비활성 전략입니다.")
    dataset = None
    if request.dataset_id is not None:
        dataset = datasets.owned(db, user_id, request.dataset_id)
        if dataset.symbol != strategy.config["symbol"]:
            raise HTTPException(422, "전략 종목과 CSV 종목이 다릅니다.")
        rows = [
            SimpleNamespace(**{**r, "opened_at": datetime.fromisoformat(r["opened_at"])})
            for r in dataset.rows
            if request.start <= datetime.fromisoformat(r["opened_at"]) < request.end
        ]
    else:
        rows = db.scalars(
            select(Candle)
            .where(
                Candle.symbol == strategy.config["symbol"],
                Candle.interval == "5m",
                Candle.source == request.source,
                Candle.complete.is_(True),
                Candle.opened_at >= request.start,
                Candle.opened_at < request.end,
                Candle.opened_at <= now() - timedelta(minutes=5),
            )
            .order_by(Candle.opened_at)
            .limit(20001)
        ).all()
    if len(rows) > 20000:
        raise HTTPException(422, "최대 20,000개 캔들까지 실행할 수 있습니다. 기간을 줄이세요.")
    contiguous = longest = 0
    prior = None
    for row in rows:
        contiguous = (
            contiguous + 1 if prior and row.opened_at - prior == timedelta(minutes=5) else 1
        )
        longest = max(longest, contiguous)
        prior = row.opened_at
    if longest <= strategy.config["slow_period"]:
        raise HTTPException(
            422, "연속된 완료 5분봉이 부족합니다. CSV를 입력하거나 합성 시연 데이터를 선택하세요."
        )
    data = [
        dict(
            opened_at=r.opened_at,
            open_won=r.open_won,
            high_won=r.high_won,
            low_won=r.low_won,
            close_won=r.close_won,
            volume=r.volume,
        )
        for r in rows
    ]
    result = simulate(data, strategy.config, request)
    if dataset is not None:
        result["dataset"] = datasets.serialize(dataset)
        result["dataset"]["created_at"] = dataset.created_at.isoformat()
        result["data_label"] = (
            "합성 CSV 데이터"
            if dataset.data_kind == "synthetic"
            else "과거 CSV 데이터 (사용자 선언·출처 미검증)"
        )
    saved = Backtest(user_id=user_id, strategy_id=strategy_id, result=result)
    db.add(saved)
    db.flush()
    return dict(id=saved.id, created_at=saved.created_at, **result)
