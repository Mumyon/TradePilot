"""Reconstructed paper trades using Toss Securities' November 16 five-minute bars."""

from datetime import datetime

from .fees import fee

_BUY_PRICE = 196500
_SELL_PRICE = 196400
_QUANTITY = 1
_PLAN = dict(entry_min_won=196000, entry_max_won=196600, max_amount_won=200000)


def entries():
    buy_fee = fee(_BUY_PRICE * _QUANTITY)
    sell_fee = fee(_SELL_PRICE * _QUANTITY)
    return [
        dict(
            sample_id="planned-buy",
            advice_comparison=dict(advice="관망", actual="매수", matched=False),
            symbol="005930",
            symbol_name="삼성전자",
            side="buy",
            quantity=_QUANTITY,
            limit_price_won=_PLAN["entry_max_won"],
            status="filled",
            created_at="2026-11-16T14:05:00+09:00",
            plan={**_PLAN, "status": "clear"},
            trade_reason="직전 봉 종가가 계획 상한에 들어와 지정가로 1주를 검토했다.",
            review_note="진입 범위 충족과 추세 반전 여부를 별도로 확인한다.",
            fill=dict(price_won=_BUY_PRICE, fee_won=buy_fee),
            market_analysis=(
                "13:55 봉은 196,900원에 마감했고 14:00 봉은 196,600원에 마감했습니다. "
                "직전 종가보다 300원 낮아 계획 상한에는 들어왔지만 하락이 멈췄다는 근거는 "
                "부족했습니다. 모의 체결은 14:05 봉 시가 196,500원을 적용했습니다."
            ),
        ),
        dict(
            sample_id="planned-exit",
            advice_comparison=dict(advice="매도", actual="매도", matched=True),
            symbol="005930",
            symbol_name="삼성전자",
            side="sell",
            quantity=_QUANTITY,
            limit_price_won=_SELL_PRICE,
            status="filled",
            created_at="2026-11-16T14:20:00+09:00",
            trade_reason="반등 폭이 작아 미리 정한 가격에 1주를 정리했다.",
            review_note="청산 기준을 정할 때 가격과 관찰 시간을 함께 적는다.",
            fill=dict(
                price_won=_SELL_PRICE,
                fee_won=sell_fee,
                realized_pnl_won=(_SELL_PRICE - _BUY_PRICE) * _QUANTITY - buy_fee - sell_fee,
            ),
            market_analysis=(
                "14:05 봉 종가 196,100원에서 14:15 봉 종가 196,350원까지 250원 반등했습니다. "
                "13:55 봉 종가 196,900원은 회복하지 못했습니다. 14:20 봉 시가 196,400원으로 "
                "정리한 경우 매매 차액은 -100원, 양쪽 수수료 포함 손익은 -160원입니다."
            ),
        ),
        dict(
            sample_id="deferred-buy",
            advice_comparison=dict(advice="관망", actual="보류", matched=True),
            symbol="005930",
            symbol_name="삼성전자",
            side="buy",
            quantity=1,
            limit_price_won=196300,
            status="deferred",
            decided_at="2026-11-16T14:30:00+09:00",
            plan=dict(status="hit", entry_min_won=195600, entry_max_won=196000),
            warning="지정가가 사전에 정한 진입 상한을 넘었습니다.",
            reason="계획 가격을 초과해 재진입을 보류했다.",
            market_analysis=(
                "14:20 봉은 197,100원까지 올랐지만 196,300원에 마감했고 "
                "14:25 봉 종가는 195,900원으로 더 낮아졌습니다. 재진입 지정가 196,300원은 "
                "계획 상한보다 300원 높았고 직전 반등을 이어간다는 근거도 부족했습니다."
            ),
        ),
    ]


def entries_in_window(start, end):
    return [
        entry
        for entry in entries()
        if start <= datetime.fromisoformat(entry.get("created_at") or entry["decided_at"]) <= end
    ]


def facts(sample):
    result = [
        dict(
            fact_id="decision",
            text="재현 모의 주문과 결정",
            evidence={
                key: sample[key] for key in ("side", "quantity", "limit_price_won", "status")
            },
        ),
        dict(
            fact_id="notes",
            text="재현 기록의 거래 이유와 복기 메모",
            evidence={"defer_reason": sample["reason"]}
            if sample["status"] == "deferred"
            else {"trade_reason": sample["trade_reason"], "review_note": sample["review_note"]},
        ),
        dict(
            fact_id="market",
            text="토스증권 5분봉 기반 ChatGPT 분석",
            evidence=sample["market_analysis"],
        ),
    ]
    if fill := sample.get("fill"):
        result.append(dict(fact_id="fill", text="재현 체결과 손익", evidence=fill))
    if plan := sample.get("plan"):
        result.append(
            dict(
                fact_id="check",
                text="재현 계획과 경고",
                evidence=dict(plan=plan, warning=sample.get("warning")),
            )
        )
    return result
