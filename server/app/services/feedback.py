"""F-05 feedback from preserved decisions, not a causal estimate of prevented trades."""

import csv
import io
import json
from collections import Counter
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from ..models import Order, OrderCheck, now

ADVICE = {
    "fomo": ("급등 추격 매수", "다음 매수 전, 급등 이전에 정한 진입 가격 범위를 확인하세요."),
    "panic": ("공포매도", "다음 매도 전, 평가손익과 사전 손절·분할청산 조건을 비교하세요."),
    "revenge": ("복수매매", "연속 손실 뒤에는 손실 만회 외의 진입 근거가 있는지 확인하세요."),
    "overtrading": ("과매매", "다음 주문 전, 최근 거래 간격과 등록된 분할 계획을 확인하세요."),
    "plan": ("매매 계획 위반", "다음 주문 전, 저장한 방향·가격 범위·누적 금액을 확인하세요."),
}
NOTES = [
    "동일 계정의 수동 점검만 집계합니다. 자동매매와 도입 전 기록은 비교에서 제외합니다.",
    "ON/OFF는 주문 당시 선택값입니다. OFF에서는 행동 경고를 평가 지표로 비교하지 않습니다.",
    "계획 준수율은 해당 점검에 연결된 체결 주문 중 계획 평가가 가능한 주문만 분모로 씁니다.",
    "자발적 보류율은 표시가 기록된 경고 중 보류·접수·체결·취소로 결정된 건 기준입니다. "
    "미결정·만료·차단·거절은 제외하며 별도 표시합니다. 재점검은 별도 시도입니다.",
    "보류는 그 점검으로 주문하지 않았다는 뜻입니다. "
    "이후 다른 점검의 재주문 방지를 뜻하지 않습니다.",
    "확인 시간은 화면 표시 보고 수신부터 결정 수신까지의 서버 시간이며 네트워크 지연을 포함합니다.",
    "차이는 관찰 기록입니다. 조건·시장 상황·순서·연습 효과를 통제한 실험이나 "
    "방지 효과 입증이 아닙니다.",
]


def ratio(n, d):
    return n / d if d else None


def records(db, user_id, days):
    end = now()
    start = end - timedelta(days=days)
    checks = db.scalars(
        select(OrderCheck)
        .where(
            OrderCheck.user_id == user_id,
            OrderCheck.created_at >= start,
            OrderCheck.created_at <= end,
        )
        .order_by(OrderCheck.created_at.desc(), OrderCheck.id.desc())
        .limit(10001)
    ).all()
    if len(checks) > 10000:
        raise HTTPException(422, "점검 기록이 10,000건을 넘습니다. 조회 기간을 줄이세요.")
    excluded = Counter(c.origin for c in checks if c.origin != "manual")
    checks = [c for c in checks if c.origin == "manual"]
    ids = [c.submitted_order_id for c in checks if c.submitted_order_id]
    orders = (
        {
            o.id: o
            for o in db.scalars(select(Order).where(Order.user_id == user_id, Order.id.in_(ids)))
        }
        if ids
        else {}
    )
    rows = []
    for c in checks:
        o = orders.get(c.submitted_order_id)
        b = c.analysis.get("behavior", {})
        enabled = c.draft.get("pilot_enabled") is True
        hits = [i["code"] for i in b.get("items", []) if i["status"] == "hit"] if enabled else []
        state = (
            "blocked"
            if not c.allowed
            else "dismissed"
            if c.decision == "dismissed" and c.decided_at and c.decided_at <= c.expires_at
            else o.status
            if o
            else "expired"
            if c.expires_at <= end
            else "pending"
        )
        presented = c.presented_at is not None
        timed = (
            presented
            and c.decided_at is not None
            and c.presented_at <= c.decided_at <= c.expires_at
        )
        snapshot = (o.analysis.get("submission") or o.analysis.get("preflight", {})) if o else {}
        plan = snapshot.get("plan")
        plan_state = (plan or {}).get("status", "unregistered")
        rows.append(
            dict(
                check_id=c.id,
                created_at=c.created_at.isoformat(),
                presented_at=c.presented_at.isoformat() if presented else None,
                decided_at=c.decided_at.isoformat() if c.decided_at else None,
                pilot_enabled=enabled,
                symbol=c.draft["symbol"],
                side=c.draft["side"],
                quantity=c.draft["quantity"],
                limit_price_won=c.draft["limit_price_won"],
                rule_version=c.analysis.get("version"),
                policy=c.analysis.get("policy"),
                source=b.get("source"),
                score=b.get("score") if enabled else None,
                partial=b.get("partial") if enabled else None,
                warnings=hits,
                rule_items=b.get("items", []) if enabled else [],
                allowed=c.allowed,
                decision=c.decision,
                decision_reason=c.decision_reason if c.decision == "dismissed" else "",
                defer_reason_recorded=bool(c.decision == "dismissed" and c.decision_reason),
                outcome=state,
                order_id=o.id if o else None,
                plan_status=plan_state
                if o
                else (c.analysis.get("plan") or {}).get("status", "unregistered"),
                plan_evaluated=bool(o and o.status == "filled" and plan_state in ("clear", "hit")),
                plan_adherent=bool(o and o.status == "filled" and plan_state == "clear"),
                warning_presented=bool(enabled and hits and c.allowed and presented),
                decision_seconds=round((c.decided_at - c.presented_at).total_seconds(), 3)
                if timed
                else None,
                trade_reason_recorded=bool(o and o.analysis.get("trade_reason", "").strip()),
                prediction_status=c.analysis.get("prediction", {}).get("status", "unavailable"),
            )
        )
    return dict(start=start, end=end, days=days), rows, dict(excluded)


def summarize(rows):
    groups = {}
    for enabled, name in [(True, "on"), (False, "off")]:
        selected = [r for r in rows if r["pilot_enabled"] == enabled]
        filled = [r for r in selected if r["outcome"] == "filled"]
        evaluated = sum(r["plan_evaluated"] for r in filled)
        adherent = sum(r["plan_adherent"] for r in filled)
        times = [r["decision_seconds"] for r in selected if r["decision_seconds"] is not None]
        groups[name] = dict(
            checks=len(selected),
            outcomes=dict(Counter(r["outcome"] for r in selected)),
            filled=len(filled),
            plan_evaluated=evaluated,
            plan_adherent=adherent,
            plan_unregistered=sum(r["plan_status"] == "unregistered" for r in filled),
            plan_unavailable=sum(
                r["plan_status"] not in ("clear", "hit", "unregistered") for r in filled
            ),
            plan_compliance=ratio(adherent, evaluated),
            decision_samples=len(times),
            mean_decision_seconds=sum(times) / len(times) if times else None,
        )
    types = []
    for code, (title, advice) in ADVICE.items():
        hits = [r for r in rows if code in r["warnings"]]
        shown = [r for r in hits if r["warning_presented"]]
        outcomes = Counter(r["outcome"] for r in shown)
        resolved = sum(outcomes[s] for s in ("dismissed", "accepted", "filled", "cancelled"))
        types.append(
            dict(
                code=code,
                title=title,
                detected=len(hits),
                presented=len(shown),
                outcomes=dict(outcomes),
                unobserved=len(hits) - len(shown),
                voluntary_resolved=resolved,
                defer_rate=ratio(outcomes["dismissed"], resolved),
                feedback=f"{title} 조건에 해당한 점검 {len(hits)}회. {advice}" if hits else None,
            )
        )
    on, off = (groups[k]["plan_compliance"] for k in ("on", "off"))
    return dict(
        groups=groups,
        warning_types=types,
        compliance_difference_pp=(on - off) * 100 if on is not None and off is not None else None,
    )


def report(db, user_id, days=30, offset=0):
    window, rows, excluded = records(db, user_id, days)
    return dict(
        window=window,
        **summarize(rows),
        excluded=excluded,
        total_checks=len(rows),
        items=rows[offset : offset + 50],
        next_offset=offset + 50 if offset + 50 < len(rows) else None,
        notes=NOTES,
    )


def export(db, user_id, days=30):
    window, rows, excluded = records(db, user_id, days)
    # No names, emails, reasons or review-note free text in research exports.
    columns = [
        "snapshot_at",
        "check_id",
        "created_at",
        "presented_at",
        "decided_at",
        "pilot_enabled",
        "symbol",
        "side",
        "quantity",
        "limit_price_won",
        "source",
        "rule_version",
        "policy",
        "score",
        "partial",
        "warnings",
        "rule_items",
        "allowed",
        "decision",
        "outcome",
        "order_id",
        "plan_status",
        "plan_evaluated",
        "plan_adherent",
        "warning_presented",
        "decision_seconds",
        "trade_reason_recorded",
        "defer_reason_recorded",
        "prediction_status",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        values = {k: row.get(k) for k in columns}
        values["snapshot_at"] = window["end"].isoformat()
        for k, value in values.items():
            if isinstance(value, (dict, list)):
                values[k] = json.dumps(value, ensure_ascii=False, sort_keys=True)
            elif isinstance(value, str) and value.startswith(
                ("=", "+", "-", "@", "\t", "\r", "\n")
            ):
                values[k] = "'" + value
        writer.writerow(values)
    return dict(
        filename="tradepilot-feedback.csv",
        csv=buffer.getvalue(),
        rows=len(rows),
        window=window,
        excluded=excluded,
        notes=NOTES,
    )
