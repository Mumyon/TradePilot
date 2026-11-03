"""Historical replay: private accounts, a virtual clock, and immutable case/model inputs.

No call here updates the live Quote/Holding/Order/Fill tables. JSON run state is
replaced under a PostgreSQL row lock; action keys and revisions prevent retries
or concurrent clients from advancing/filling twice.
"""

import copy
import csv
import hashlib
import io
import json
import math
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from ..ml import pipeline as ml
from ..models import ReplayCase, ReplayRun, new_id, now
from . import datasets, replay_feedback, replay_predictions, risk
from .fees import fee, reserve
from .orders import lock_user

KST = ZoneInfo("Asia/Seoul")
VERSION = "replay-v1"
EVENTS = [
    dict(
        key="covid_2020",
        name="2020년 3월 코로나19 시장 충격",
        source_url="https://www.fsc.go.kr/po010101/74223",
        status="awaiting_csv",
        note="사건 참고 자료만 제공됩니다. 종목별 실제 5분봉 CSV를 등록하세요.",
    ),
    dict(
        key="selloff_2024",
        name="2024년 8월 5일 증시 급락",
        source_url="https://www.fsc.go.kr/no010101/82809",
        status="awaiting_csv",
        note="사건 참고 자료만 제공됩니다. 종목별 실제 5분봉 CSV를 등록하세요.",
    ),
]
CONFIG = dict(
    initial_cash_won=10_000_000,
    order_limit_won=1_000_000,
    daily_loss_limit_won=1_000_000,
    cooldown_seconds=300,
    fee_rate="0.00015",
    execution="next_bar_open_limit_no_slippage",
    max_actions=2000,
    version=VERSION,
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def stamp(value):
    return datetime.fromisoformat(value)


def bars(rows):
    return [ml.Bar(stamp(r["opened_at"]), *(r[k] for k in datasets.FIELDS[1:])) for r in rows]


def case_owned(db, uid, cid, *, lock=False):
    query = select(ReplayCase).where(ReplayCase.id == cid, ReplayCase.user_id == uid)
    item = db.scalar(query.with_for_update() if lock else query)
    if item is None:
        raise HTTPException(404, "사례를 찾을 수 없습니다.")
    return item


def run_owned(db, uid, rid, *, lock=False):
    query = select(ReplayRun).where(ReplayRun.id == rid, ReplayRun.user_id == uid)
    item = db.scalar(query.with_for_update() if lock else query)
    if item is None:
        raise HTTPException(404, "모의실험을 찾을 수 없습니다.")
    return item


def case_view(c):
    a = c.artifact
    return dict(
        id=c.id,
        **{k: v for k, v in c.config.items() if k != "daily_cross_check"},
        model=None
        if a is None
        else dict(
            version=a["version"],
            data_end=a["data_end"],
            quality_gate_passed=a["quality_gate_passed"],
            evaluation=a["evaluation"],
            features=a["features"],
            labels=a["labels"],
        ),
        preview=c.rows[max(0, c.config["start"] - 34) : c.config["start"] + 1],
    )


def create_case(db, uid, body):
    lock_user(db, uid)
    dataset = datasets.owned(db, uid, body.dataset_id)
    if body.replay_from.tzinfo is None:
        raise HTTPException(422, "재생 시작 시각에 시간대를 포함하세요.")
    rows = dataset.rows
    starts = [i for i, r in enumerate(rows) if stamp(r["opened_at"]) == body.replay_from]
    if not starts or not 35 <= starts[0] < len(rows) - 1:
        raise HTTPException(422, "시작 봉은 CSV에 존재하고 앞에 35봉·뒤에 1봉 이상이 필요합니다.")
    start = starts[0]
    if start > 5000 or len(rows) - start > 500:
        raise HTTPException(422, "학습 구간 최대 5,000봉, 재생 구간 최대 500봉으로 나눠 주세요.")
    config = dict(
        name=body.name,
        symbol=dataset.symbol,
        provider=dataset.provider,
        data_kind=dataset.data_kind,
        event_key=body.event_key,
        source_url=body.source_url,
        start=start,
        bar_count=len(rows),
        replay_from=rows[start]["opened_at"],
        end=rows[-1]["opened_at"],
        data_sha256=digest(rows),
        dataset_sha256=dataset.summary["sha256"],
        provenance="사용자 등록 · 가격 정확성/이용권한은 별도 확인 필요",
    )
    existing = db.scalars(select(ReplayCase).where(ReplayCase.user_id == uid)).all()
    for c in existing:
        if c.config == config:
            return case_view(c)
    if len(existing) >= 50:
        raise HTTPException(409, "사례는 최대 50개까지 저장할 수 있습니다.")
    c = ReplayCase(user_id=uid, config=config, rows=copy.deepcopy(rows))
    db.add(c)
    db.flush()
    return case_view(c)


def practice(db, uid):
    lock_user(db, uid)
    for c in db.scalars(select(ReplayCase).where(ReplayCase.user_id == uid)):
        if c.config.get("generator") == "synthetic-practice-v1":
            return case_view(c)
    # Entirely invented prices. No values are claimed to reproduce a real security/event.
    rows, day, n = [], datetime(2024, 1, 2, 9, tzinfo=KST), 0
    while n < 19:
        if day.weekday() < 5:
            price = 70000
            for j in range(78):
                opening = price
                drift = [0.0012, -0.0012, 0.00002][n % 3]
                change = drift + 0.0003 * math.sin(j * 0.8)
                if n == 18:
                    change = 0.020 if 39 <= j <= 42 else -0.023 if 47 <= j <= 51 else 0.0001
                price = max(1000, round(price * (1 + change)))
                rows.append(
                    dict(
                        zip(
                            datasets.FIELDS,
                            [
                                (day + timedelta(minutes=j * 5)).astimezone(UTC).isoformat(),
                                opening,
                                max(opening, price) + 20,
                                min(opening, price) - 20,
                                price,
                                100000 + j * 100 + (300000 if abs(change) > 0.01 else 0),
                            ],
                        )
                    )
                )
            n += 1
        day += timedelta(days=1)
    start = 18 * 78 + 35
    c = ReplayCase(
        user_id=uid,
        rows=rows,
        config=dict(
            name="합성 연습 · 급등 추격과 급락 대응",
            symbol="005930",
            provider="synthetic-practice-v1",
            generator="synthetic-practice-v1",
            data_kind="synthetic",
            event_key="practice",
            source_url="",
            start=start,
            bar_count=len(rows),
            replay_from=rows[start]["opened_at"],
            end=rows[-1]["opened_at"],
            data_sha256=digest(rows),
            provenance="가상의 가격 · 실제 과거 사례 또는 연구 실측 아님",
        ),
    )
    db.add(c)
    db.flush()
    train_case(db, uid, c.id)
    return case_view(c)


def train_case(db, uid, cid):
    c = case_owned(db, uid, cid, lock=True)
    if c.artifact is not None:
        return case_view(c)
    if db.scalar(select(ReplayRun.id).where(ReplayRun.case_id == cid).limit(1)):
        raise HTTPException(
            409, "실험을 시작한 사례의 모델은 변경할 수 없습니다. 새 사례를 만드세요."
        )
    prefix = c.rows[: c.config["start"]]
    try:
        c.artifact = ml.train(
            bars(prefix),
            c.config["symbol"],
            c.config["provider"],
            c.config["data_kind"],
            digest(prefix),
        )
    except ValueError as exc:
        raise HTTPException(
            422, f"학습 불가: {exc}. 여러 거래일의 학습용 CSV가 필요합니다."
        ) from None
    db.flush()
    return case_view(c)


def prediction(c, s):
    a, cursor = c.artifact, s["cursor"]
    row = bars([c.rows[cursor]])[0]
    unavailable = dict(status="unavailable", message="학습 모델 없음 · 행동 규칙은 사용 가능")
    if a is None:
        return unavailable
    common = dict(
        model_version=a["version"],
        data_kind=c.config["data_kind"],
        training_end=a["data_end"],
        as_of=row.as_of.isoformat(),
    )
    if stamp(a["data_end"]) > row.opened_at:
        return dict(**common, status="unavailable", message="학습·재생 구간 중첩")
    if row.as_of.astimezone(KST).hour * 60 + row.as_of.astimezone(KST).minute > 14 * 60 + 30:
        return dict(**common, status="unavailable", message="장 종료까지 1시간 미만 · 예측 보류")
    # Never include any unseen bar, even for feature engineering.
    features = ml.feature_rows(bars(c.rows[: cursor + 1]))
    if not features or features[-1]["as_of"] != row.as_of:
        return dict(**common, status="unavailable", message="연속 완료 5분봉 35개가 필요합니다.")
    if row.as_of + timedelta(hours=1) > stamp(c.rows[-1]["opened_at"]) + timedelta(minutes=5):
        return dict(
            **common, status="unavailable", message="재생 자료 종료까지 1시간 미만 · 예측 보류"
        )
    if not a["quality_gate_passed"]:
        return dict(**common, status="unavailable", message="검증 기준 미달 · 예측 보류")
    probs = ml.predict(a["model"], features[-1])
    index = max(range(3), key=lambda i: probs[i])
    direction = ml.LABELS[index] if max(probs) >= 0.65 else "abstain"
    return dict(
        **common,
        status="available",
        target_at=(row.as_of + timedelta(hours=1)).isoformat(),
        horizon_minutes=60,
        threshold_percent=0.5,
        direction_threshold=0.65,
        direction=direction,
        probabilities=dict(zip(ml.LABELS, probs)),
        indicators=features[-1]["indicators"],
        message="1시간 방향 확률 · 65% 미만 판단 보류 · 매매 권유 아님",
        factors="MA/RSI/MACD는 입력 지표이며 모델의 인과적 설명이 아닙니다.",
    )


def start(db, uid, cid, body):
    lock_user(db, uid)
    c = case_owned(db, uid, cid, lock=True)
    runs = db.scalars(select(ReplayRun).where(ReplayRun.user_id == uid)).all()
    request = dict(case_id=cid, **body.model_dump(mode="json"))
    for r in runs:
        if r.state["start_request"]["request_id"] == body.request_id:
            if r.state["start_request"] != request:
                raise HTTPException(409, "동일 요청 키의 내용이 다릅니다.")
            return view(c, r)
    if len(runs) >= 100:
        raise HTTPException(409, "사용자당 실험 최대 100회입니다.")
    plan = None if body.plan is None else body.plan.model_dump()
    pilot_enabled = secrets.choice((True, False)) if body.randomize_order else body.pilot_enabled
    pair = None
    behavior_policy = dict(version=risk.VERSION, policy=copy.deepcopy(risk.POLICY))
    if body.paired_run_id:
        pair = run_owned(db, uid, body.paired_run_id)
        if (
            pair.case_id != cid
            or not pair.state["finished"]
            or pair.state["pilot_enabled"] == pilot_enabled
        ):
            raise HTTPException(409, "완료한 동일 사례의 반대 Pilot 조건으로 시작하세요.")
        if pair.state["sequence"] != 1 or any(
            r.id != pair.id and r.state["pair_id"] == pair.state["pair_id"] for r in runs
        ):
            raise HTTPException(409, "실험 쌍은 ON/OFF 각 1회입니다. 기존 실행을 이어가세요.")
        if pair.state.get("behavior_policy") != behavior_policy:
            raise HTTPException(
                409, "이전 실험의 규칙 버전을 확인할 수 없거나 변경되었습니다. 새 쌍을 시작하세요."
            )
        plan = copy.deepcopy(pair.state["plan"])
    if plan:
        plan.update(id="session-plan", created_at=c.rows[c.config["start"]]["opened_at"])
    comparison = digest(
        dict(
            case_sha=c.config["data_sha256"],
            start=c.config["start"],
            model=c.artifact["version"] if c.artifact else None,
            config=CONFIG,
            plan=plan,
            behavior_policy=behavior_policy,
        )
    )
    if pair and comparison != pair.state["comparison_key"]:
        raise HTTPException(409, "사례·모델·설정이 이전 실험과 다릅니다. 새 쌍을 시작하세요.")
    r = ReplayRun(
        user_id=uid,
        case_id=cid,
        state=dict(
            start_request=request,
            revision=0,
            cursor=c.config["start"],
            pilot_enabled=pilot_enabled,
            plan=plan,
            config=CONFIG,
            behavior_policy=behavior_policy,
            cash=CONFIG["initial_cash_won"],
            quantity=0,
            cost=0,
            finished=False,
            checks=[],
            orders=[],
            requests={},
            equity=[],
            comparison_key=comparison,
            paired_run_id=pair.id if pair else None,
            pair_id=pair.state["pair_id"] if pair else new_id(),
            sequence=pair.state["sequence"] + 1 if pair else 1,
            allocation_method=(
                pair.state.get("allocation_method", "user_selected")
                if pair
                else "server_randomized"
                if body.randomize_order
                else "user_selected"
            ),
            condition_order=(
                pair.state.get("condition_order")
                if pair
                else ["ON", "OFF"]
                if pilot_enabled
                else ["OFF", "ON"]
            ),
            allocation_at=(
                pair.state.get("allocation_at")
                if pair
                else now().isoformat()
                if body.randomize_order
                else None
            ),
        ),
    )
    db.add(r)
    db.flush()
    r.state = {**r.state, "equity": [equity(c, r.state)]}
    return view(c, r)


def virtual_at(c, s):
    return stamp(c.rows[s["cursor"]]["opened_at"]) + timedelta(minutes=5)


def equity(c, s):
    return dict(
        at=virtual_at(c, s).isoformat(),
        value=s["cash"] + s["quantity"] * c.rows[s["cursor"]]["close_won"],
    )


def analysis(c, s, action, *, shadow=False):
    at = virtual_at(c, s)
    price = c.rows[s["cursor"]]["close_won"]
    q = NS(price_won=price, as_of=at, source=c.config["provider"])
    plan = NS(**s["plan"]) if s["plan"] and s["plan"]["side"] == action.side else None
    if plan:
        plan.created_at = stamp(plan.created_at)
    draft = NS(
        side=action.side,
        pilot_enabled=True if shadow else s["pilot_enabled"],
        plan_id=plan.id if plan else None,
    )
    ps, pm, stop = "unregistered", "계획 미등록", False
    spent = sum(
        o["quantity"] * o["price"]
        for o in s["orders"]
        if o["status"] in ("accepted", "filled") and o["side"] == (plan.side if plan else "")
    )
    if plan:
        stop = (
            action.side == "sell" and plan.stop_loss_won is not None and price <= plan.stop_loss_won
        )
        if action.side != plan.side:
            ps, pm = "hit", "사전 계획의 주문 방향과 다릅니다."
        elif spent + action.quantity * action.limit_price_won > plan.max_amount_won:
            ps, pm = "hit", "계획 누적 금액 한도를 초과합니다."
        elif stop:
            ps, pm = "clear", "사전에 등록한 손절 기준에 따른 매도입니다."
        elif (
            min(price, action.limit_price_won) < plan.entry_min_won
            or max(price, action.limit_price_won) > plan.entry_max_won
        ):
            ps, pm = "hit", "현재가 또는 지정가가 계획 범위를 벗어납니다."
        else:
            ps, pm = "clear", "사전 계획 조건을 충족합니다."
    base_at, change = None, None
    if s["cursor"] >= 2:
        base = c.rows[s["cursor"] - 2]
        if stamp(base["opened_at"]) + timedelta(minutes=15) == at:
            base_at = at - timedelta(minutes=10)
            change = Decimal(price - base["close_won"]) * 100 / Decimal(base["close_won"])
    orders = s["orders"]
    recent = [o for o in orders if stamp(o["at"]) > at - timedelta(hours=1)]
    group = plan.id if plan and ps == "clear" and plan.split_order else None
    count = len({o.get("group") or o["id"] for o in recent} | {group or "current-request"})
    sold = [o for o in orders if o["side"] == "sell" and o["status"] == "filled"]
    sold.sort(key=lambda o: o["fill_at"], reverse=True)
    losses = [NS(realized_pnl_won=o["pnl"], created_at=stamp(o["fill_at"])) for o in sold[:3]]
    day_start = at.astimezone(KST).replace(hour=0, minute=0, second=0).astimezone(UTC)
    daily = sum(o["pnl"] for o in sold if stamp(o["fill_at"]) >= day_start)
    last = next(
        (NS(created_at=stamp(o["at"])) for o in reversed(orders) if o["side"] == action.side), None
    )
    position = price * s["quantity"] - s["cost"]
    user = NS(
        **{k: s["config"][k] for k in ["cooldown_seconds", "daily_loss_limit_won"]},
        trading_paused=False,
    )
    result = risk.assess(
        at=at,
        quote=q,
        draft=draft,
        plan=plan,
        plan_state=ps,
        plan_message=pm,
        stop=stop,
        base_at=base_at,
        change=change,
        position_loss=position < 0 if s["quantity"] else None,
        position_return=Decimal(position) * 100 / Decimal(s["cost"]) if s["cost"] else None,
        recent_losses=losses,
        count=count,
        group=group,
        day_start=day_start,
        known=True,
        pnl=daily,
        last=last,
        user=user,
        settings=NS(orders_halted=False),
    )
    pending = [o for o in orders if o["status"] == "accepted"]
    cash_reserved = sum(reserve(o["price"] * o["quantity"]) for o in pending if o["side"] == "buy")
    qty_reserved = sum(o["quantity"] for o in pending if o["side"] == "sell")
    reasons = result["risk"]["reasons"]
    amount = action.quantity * action.limit_price_won
    if amount > s["config"]["order_limit_won"]:
        reasons.append("주문당 1,000,000원 한도 초과")
    if action.side == "buy" and reserve(amount) > s["cash"] - cash_reserved:
        reasons.append("주문 가능 현금 부족")
    if action.side == "sell" and action.quantity > s["quantity"] - qty_reserved:
        reasons.append("주문 가능 보유 수량 부족")
    if s["cursor"] >= len(c.rows) - 1:
        reasons.append("마지막 봉입니다. 실험을 종료하세요.")
    result["prediction"] = prediction(c, s)
    return result


def check_public(check):
    return {k: v for k, v in check.items() if k != "shadow"}


def apply(db, uid, rid, body):
    r = run_owned(db, uid, rid, lock=True)
    c = case_owned(db, uid, r.case_id)
    s = copy.deepcopy(r.state)
    payload = body.model_dump(mode="json")
    previous = s["requests"].get(body.request_id)
    if previous:
        if previous["hash"] != digest(payload):
            raise HTTPException(409, "동일 요청 키의 내용이 다릅니다.")
        return dict(**view(c, r), action_result=previous["result"])
    if s["finished"]:
        raise HTTPException(409, "종료된 실험입니다.")
    if body.action in ("check", "submit") and s.get("behavior_policy") not in (
        None,
        dict(version=risk.VERSION, policy=risk.POLICY),
    ):
        raise HTTPException(409, "행동 규칙이 변경되었습니다. 실험을 종료하고 새 쌍을 시작하세요.")
    if body.revision != s["revision"]:
        raise HTTPException(
            409, "다른 요청으로 상태가 변경되었습니다. 새로고침 후 다시 실행하세요."
        )
    if len(s["requests"]) >= CONFIG["max_actions"] and body.action != "finish":
        raise HTTPException(409, "실험 동작 한도에 도달했습니다. 종료 후 새 실험을 시작하세요.")
    result = {}
    if body.action == "advance":
        if s["cursor"] >= len(c.rows) - 1:
            raise HTTPException(409, "마지막 봉입니다. 실험을 종료하세요.")
        previous_open = stamp(c.rows[s["cursor"]]["opened_at"])
        s["cursor"] += 1
        row = c.rows[s["cursor"]]
        gap = stamp(row["opened_at"]) - previous_open != timedelta(minutes=5)
        s["market_notice"] = None
        if gap:
            s["market_notice"] = (
                "시세 단절 구간입니다. 미체결 주문을 취소하고 다음 관측 봉으로 이동했습니다."
            )
            s.setdefault("market_gaps", []).append(
                dict(
                    previous_open=previous_open.isoformat(),
                    next_open=row["opened_at"],
                    action="cancel_pending_without_assuming_fill",
                )
            )

        price = row["open_won"]
        for o in s["orders"]:
            if o["status"] != "accepted":
                continue
            if gap:
                o.update(status="cancelled", cancellation_reason="시세 단절 · 체결 재현 불가")
                continue
            # A previously unknown NEXT bar open is the only execution price.
            if (o["side"] == "buy" and price > o["price"]) or (
                o["side"] == "sell" and price < o["price"]
            ):
                continue
            amount = price * o["quantity"]
            commission = fee(amount)
            pnl = None
            if o["side"] == "buy":
                s["cash"] -= amount + commission
                s["quantity"] += o["quantity"]
                s["cost"] += amount + commission
            else:
                basis = s["cost"] * o["quantity"] // s["quantity"]
                pnl = amount - commission - basis
                s["cash"] += amount - commission
                s["quantity"] -= o["quantity"]
                s["cost"] -= basis
            o.update(
                status="filled", fill_price=price, fee=commission, pnl=pnl, fill_at=row["opened_at"]
            )
        for check in s["checks"]:
            if check["decision"] == "pending":
                check["decision"] = "expired"
        s["equity"].append(equity(c, s))
    elif body.action == "check":
        assessed = analysis(c, s, body)
        check = dict(
            check_id=new_id(),
            allowed=not assessed["risk"]["reasons"],
            analysis=assessed,
            shadow=analysis(c, s, body, shadow=True),
            messages=assessed["risk"]["reasons"] + risk.messages(assessed),
            expires_at=(now() + timedelta(seconds=60)).isoformat(),
            cursor=s["cursor"],
            decision="pending",
            created_at=now().isoformat(),
            virtual_at=virtual_at(c, s).isoformat(),
            presented_at=None,
            decided_at=None,
            draft=dict(side=body.side, quantity=body.quantity, price=body.limit_price_won),
        )
        s["checks"].append(check)
        result = check_public(check)
    elif body.action in ("presented", "submit", "defer", "close"):
        check = next((x for x in s["checks"] if x["check_id"] == body.check_id), None)
        if check is None:
            raise HTTPException(404, "점검을 찾을 수 없습니다.")
        if check["decision"] != "pending" or check["cursor"] != s["cursor"]:
            raise HTTPException(409, "이미 처리되었거나 시간이 진행된 점검입니다.")
        if body.action == "presented":
            check["presented_at"] = check["presented_at"] or now().isoformat()
        elif body.action in ("defer", "close"):
            check.update(
                decision="deferred" if body.action == "defer" else "closed",
                decided_at=now().isoformat(),
                decision_reason=body.reason.strip() if body.action == "defer" else "",
            )
        else:
            if stamp(check["expires_at"]) < now():
                raise HTTPException(409, "점검 유효시간이 지났습니다. 다시 점검하세요.")
            if check["draft"] != dict(
                side=body.side, quantity=body.quantity, price=body.limit_price_won
            ):
                raise HTTPException(409, "점검한 주문 내용과 다릅니다.")
            assessed = analysis(c, s, body)
            if assessed["risk"]["reasons"]:
                raise HTTPException(409, " / ".join(assessed["risk"]["reasons"]))
            behavior = assessed["behavior"]
            if behavior["score"] > check["analysis"]["behavior"]["score"]:
                raise HTTPException(409, "위험 점수가 변경되었습니다. 다시 점검하세요.")
            if behavior["requires_ack"] and (
                not check["presented_at"]
                or not body.warning_acknowledged
                or len(body.reason.strip()) < 3
            ):
                raise HTTPException(422, "경고 확인과 3자 이상의 거래 이유가 필요합니다.")
            if behavior["requires_high_ack"] and not body.high_risk_acknowledged:
                raise HTTPException(422, "높음 단계 추가 확인이 필요합니다.")
            order = dict(
                id=new_id(),
                **check["draft"],
                status="accepted",
                at=virtual_at(c, s).isoformat(),
                check_id=check["check_id"],
                group=assessed["plan_group_id"],
                analysis=assessed,
                reason=body.reason.strip(),
                submitted_at=now().isoformat(),
            )
            s["orders"].append(order)
            check.update(
                decision="submitted",
                decided_at=now().isoformat(),
                order_id=order["id"],
                decision_reason=body.reason.strip(),
            )
            result = dict(order_id=order["id"], status="accepted")
    elif body.action == "cancel":
        order = next((o for o in s["orders"] if o["id"] == body.order_id), None)
        if order is None or order["status"] != "accepted":
            raise HTTPException(409, "취소 가능한 주문이 아닙니다.")
        order.update(status="cancelled", cancelled_at=now().isoformat())
    elif body.action == "finish":
        for o in s["orders"]:
            if o["status"] == "accepted":
                o.update(status="cancelled", cancellation_reason="실험 종료")
        for check in s["checks"]:
            if check["decision"] == "pending":
                check["decision"] = "unresolved_at_finish"
        s.update(finished=True, finished_at=now().isoformat())
    s["revision"] += 1
    s["requests"][body.request_id] = dict(hash=digest(payload), result=result)
    r.state = s
    db.flush()
    return dict(**view(c, r), action_result=result)


def summary(c, s):
    filled = [o for o in s["orders"] if o["status"] == "filled"]
    evaluated = [o for o in filled if o["analysis"]["context"]["plan_status"] in ("clear", "hit")]
    compliant = sum(o["analysis"]["context"]["plan_status"] == "clear" for o in evaluated)
    # Same rule applies retrospectively in both conditions; never exposed during OFF.
    qualified = [x for x in s["checks"] if x["shadow"]["behavior"]["requires_ack"] and x["allowed"]]
    presented = [x for x in qualified if x["presented_at"] and s["pilot_enabled"]]
    times = [
        (stamp(x["decided_at"]) - stamp(x["presented_at"])).total_seconds()
        for x in s["checks"]
        if x["presented_at"] and x["decided_at"]
    ]
    peak, drawdown = s["config"]["initial_cash_won"], 0.0
    for e in s["equity"]:
        peak = max(peak, e["value"])
        drawdown = max(drawdown, (peak - e["value"]) / peak)
    return dict(
        accepted_orders=len(s["orders"]),
        filled_orders=len(filled),
        plan_evaluated_fills=len(evaluated),
        plan_compliant_fills=compliant,
        plan_unregistered_fills=sum(
            o["analysis"]["context"]["plan_status"] == "unregistered" for o in filled
        ),
        plan_unavailable_fills=sum(
            o["analysis"]["context"]["plan_status"] not in ("clear", "hit", "unregistered")
            for o in filled
        ),
        plan_compliance_rate=compliant / len(evaluated) if evaluated else None,
        rule_qualified_checks=len(qualified),
        rule_qualified_submissions=sum(x["decision"] == "submitted" for x in qualified),
        warnings_presented=len(presented),
        warned_deferrals=sum(x["decision"] == "deferred" for x in presented),
        explicit_deferrals=sum(x["decision"] == "deferred" for x in s["checks"]),
        decision_seconds_mean=sum(times) / len(times) if times else None,
        decision_timed_count=len(times),
        final_equity_won=equity(c, s)["value"],
        return_percent=(equity(c, s)["value"] / s["config"]["initial_cash_won"] - 1) * 100,
        max_drawdown_percent=drawdown * 100,
        prediction_review=replay_predictions.review(c, s)["summary"],
        warning_types=replay_feedback.breakdown(s),
        warning=(
            "반복 점검은 독립 표본이 아닙니다. "
            "관찰 지표만으로 뇌동매매 감소의 인과 효과를 결론낼 수 없습니다."
        ),
    )


def decision_log(s):
    orders = {o["check_id"]: o for o in s["orders"]}
    return [
        dict(
            check_id=c["check_id"],
            virtual_at=c["virtual_at"],
            decision=c["decision"],
            reason=c.get("decision_reason", orders.get(c["check_id"], {}).get("reason", "")),
        )
        for c in s["checks"]
    ]


def view(c, r):
    s = r.state
    pending = [o for o in s["orders"] if o["status"] == "accepted"]
    return dict(
        id=r.id,
        case_id=c.id,
        case_name=c.config["name"],
        symbol=c.config["symbol"],
        data_kind=c.config["data_kind"],
        provenance=c.config["provenance"],
        interval=c.config.get("interval", "5m"),
        data_notice=c.config.get("data_notice"),
        market_notice=s.get("market_notice"),
        source_url=c.config.get("source_url"),
        revision=s["revision"],
        cursor=s["cursor"],
        step=s["cursor"] - c.config["start"],
        total_steps=len(c.rows) - c.config["start"] - 1,
        virtual_at=virtual_at(c, s).isoformat(),
        pilot_enabled=s["pilot_enabled"],
        finished=s["finished"],
        plan=s["plan"],
        config=s["config"],
        pair_id=s["pair_id"],
        sequence=s["sequence"],
        allocation_method=s.get("allocation_method", "user_selected"),
        condition_order=s.get("condition_order"),
        allocation_at=s.get("allocation_at"),
        comparison_key=s["comparison_key"],
        cash_won=s["cash"],
        quantity=s["quantity"],
        cost_won=s["cost"],
        available_cash_won=s["cash"]
        - sum(reserve(o["price"] * o["quantity"]) for o in pending if o["side"] == "buy"),
        equity_won=equity(c, s)["value"],
        visible_bars=c.rows[max(0, c.config["start"] - 34) : s["cursor"] + 1],
        prediction=prediction(c, s),
        orders=s["orders"],
        summary=summary(c, s) if s["finished"] else None,
        prediction_review=replay_predictions.review(c, s) if s["finished"] else None,
        decisions=decision_log(s) if s["finished"] else None,
    )


def export(db, uid, rid):
    from .ai_review import exported

    r = run_owned(db, uid, rid)
    c = case_owned(db, uid, r.case_id)
    if not r.state["finished"]:
        raise HTTPException(409, "실험 종료 후 연구 자료를 내보낼 수 있습니다.")
    s = r.state
    prediction_review = replay_predictions.review(c, s)
    outcomes = {
        check_id: observation["outcome"]
        for observation in prediction_review["observations"]
        for check_id in observation["check_ids"]
    }
    evidence = dict(
        schema=VERSION,
        participant_id=uid,
        run_id=r.id,
        created_at=r.created_at,
        case=c.config,
        case_rows=c.rows,
        model=c.artifact,
        state={k: v for k, v in s.items() if k != "requests"},
        summary=summary(c, s),
        prediction_review=prediction_review,
        ai_review=exported(db, r.id),
    )
    fields = [
        "participant_id",
        "pair_id",
        "run_id",
        "sequence",
        "allocation_method",
        "condition_order",
        "comparison_key",
        "data_kind",
        "case_sha256",
        "pilot_enabled",
        "check_id",
        "virtual_at",
        "presented_at",
        "decided_at",
        "decision",
        "decision_seconds",
        "side",
        "quantity",
        "price",
        "rule_version",
        "shadow_score",
        "warning_shown",
        "plan_status",
        "order_id",
        "order_status",
        "fill_price",
        "fee",
        "pnl",
        "reason",
        "model_version",
        "prediction_as_of",
        "prediction_direction",
        "prediction_outcome_status",
        "prediction_target_at",
        "prediction_actual_direction",
        "prediction_correct",
        "prediction_return_percent",
    ]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for check in s["checks"]:
        o = next((o for o in s["orders"] if o["check_id"] == check["check_id"]), {})
        delta = (
            (stamp(check["decided_at"]) - stamp(check["presented_at"])).total_seconds()
            if check["decided_at"] and check["presented_at"]
            else None
        )
        values = dict(
            participant_id=uid,
            pair_id=s["pair_id"],
            run_id=r.id,
            sequence=s["sequence"],
            allocation_method=s.get("allocation_method", "user_selected"),
            condition_order="→".join(s.get("condition_order") or []),
            comparison_key=s["comparison_key"],
            data_kind=c.config["data_kind"],
            case_sha256=c.config["data_sha256"],
            pilot_enabled=s["pilot_enabled"],
            **{
                k: check.get(k)
                for k in ["check_id", "virtual_at", "presented_at", "decided_at", "decision"]
            },
            decision_seconds=delta,
            **check["draft"],
            rule_version=check["shadow"].get("version"),
            shadow_score=check["shadow"]["behavior"]["score"],
            warning_shown=bool(
                s["pilot_enabled"]
                and check["presented_at"]
                and check["shadow"]["behavior"]["requires_ack"]
            ),
            plan_status=check["analysis"]["context"]["plan_status"],
            order_id=o.get("id"),
            order_status=o.get("status"),
            **{k: o.get(k) for k in ["fill_price", "fee", "pnl"]},
            reason=check.get("decision_reason", o.get("reason", "")),
            model_version=check["analysis"]["prediction"].get("model_version"),
            prediction_as_of=check["analysis"]["prediction"].get("as_of"),
            prediction_direction=check["analysis"]["prediction"].get("direction"),
            prediction_outcome_status=outcomes.get(check["check_id"], {}).get(
                "status", "no_prediction"
            ),
            **{
                "prediction_" + key: outcomes.get(check["check_id"], {}).get(key)
                for key in ["target_at", "actual_direction", "correct", "return_percent"]
            },
        )
        # Prevent spreadsheet formula execution in user-authored text.
        writer.writerow(
            {
                k: "'" + v
                if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                else v
                for k, v in values.items()
            }
        )
    return dict(csv=out.getvalue(), evidence=evidence)
