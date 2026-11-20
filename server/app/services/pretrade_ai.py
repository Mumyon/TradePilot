"""Queue ChatGPT web research with a minimal, timestamped order context."""

import copy
import hashlib
import json
from datetime import timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from ..brokers.contracts import accepts_source
from ..llm import chatgpt, review_provider
from ..models import AIReview, OrderCheck, Quote, Symbol, User, now
from . import decision_ai
from .ai_review import MESSAGES, enforce_daily_limit, status_view
from .quant_analysis import PROMPT as INSTRUCTIONS
from .quant_analysis import VERSION

WEB_ORDER_PROMPT = (
    INSTRUCTIONS + "\n매매 직전 주문 검토입니다. 현재 시세와 지정가의 차이를 먼저 설명하세요."
    " 진행 전 확인할 조건을 알려주세요."
)


VERDICT_INSTRUCTION = (
    "\n첫 줄에 PILOT_SIGNAL=관망 형식으로 매수, 매도, 관망, 보류, 데이터 부족 중 "
    "하나를 명시하세요. 조건 충족을 기다려야 한다면 관망 또는 보류를 선택하세요."
)


def owned(db, user_id, check_id):
    check = db.scalar(
        select(OrderCheck).where(OrderCheck.id == check_id, OrderCheck.user_id == user_id)
    )
    if check is None:
        raise HTTPException(404, "주문 점검을 찾을 수 없습니다.")
    return check


def frozen_input(db, check, settings):
    q = db.get(Quote, check.draft["symbol"])
    instrument = db.get(Symbol, check.draft["symbol"])
    fresh = (
        q is not None
        and accepts_source(q.source, settings)
        and 0 <= (now() - q.as_of).total_seconds() <= settings.quote_max_age_seconds
    )
    return dict(
        schema=VERSION,
        instrument=dict(symbol=check.draft["symbol"], name=instrument.name),
        order_side=check.draft["side"],
        current_price=q.price_won if fresh else None,
        quote_as_of=q.as_of.isoformat() if q else None,
        quote_fresh=fresh,
        quote_source=q.source if q else None,
        analysis_as_of=now().isoformat(),
        research_window=dict(
            start=(now().date() - timedelta(days=365)).isoformat(), end=now().date().isoformat()
        ),
        facts=[],
        note="종목, 시세와 주문 가격을 검토합니다. 계좌정보·자유입력은 제공하지 않습니다.",
    )


def review_status(db, user_id, check_id, settings):
    check = owned(db, user_id, check_id)
    if check.consumed or check.expires_at <= now():
        return dict(
            status="expired", message="주문 점검이 만료됐습니다. 시세와 피드백을 다시 확인하세요."
        )
    record = db.scalar(select(AIReview).where(AIReview.check_id == check_id))
    if record:
        if record.data.get("prompt_version") != VERSION:
            return dict(status="expired", message="새 정량 분석으로 다시 점검해 주세요.")
        return dict(**status_view(record), valid_until=check.expires_at)
    if not settings.ai_review_enabled:
        return dict(status="unavailable", reason="disabled", message=MESSAGES["disabled"])
    try:
        connection = review_provider.connection(settings, user_id)
    except chatgpt.ReviewError as exc:
        return dict(status="unavailable", reason=exc.code, message=MESSAGES.get(exc.code))
    return dict(
        status="ready",
        requested_model=connection["model"],
        message="현재 주문의 실시간 판단 피드백을 받을 수 있습니다.",
    )


def request_review(db, user_id, check_id, settings):
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    check = owned(db, user_id, check_id)
    record = db.scalar(select(AIReview).where(AIReview.check_id == check_id).with_for_update())
    if record and record.data.get("prompt_version") != VERSION:
        raise HTTPException(409, "새 정량 분석으로 다시 점검해 주세요.")
    if record and record.status != "failed":
        return status_view(record)
    if not settings.ai_review_enabled:
        raise HTTPException(409, MESSAGES["disabled"])
    if check.consumed or check.expires_at <= now():
        raise HTTPException(409, "주문 점검이 만료됐습니다. 다시 점검해 주세요.")
    if record and record.attempts >= 2:
        raise HTTPException(429, MESSAGES["attempt_limit"])
    try:
        connected = review_provider.connection(settings, user_id)
    except chatgpt.ReviewError as exc:
        raise HTTPException(409, MESSAGES.get(exc.code, MESSAGES["not_connected"])) from None
    at = now()
    if settings.ai_review_provider == "openai_api":
        enforce_daily_limit(db, user_id, at, limit=12)
    if record is None:
        payload = frozen_input(db, check, settings)
        payload["limit_price_won"] = int(check.draft["limit_price_won"])
        prior = decision_ai.latest_market_context(db, user_id, check.draft["symbol"])
        if prior:
            payload["prior_market_analysis"] = prior
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        record = AIReview(
            check_id=check_id,
            user_id=user_id,
            status="pending",
            attempts=1,
            data=dict(
                input=payload,
                input_sha256=hashlib.sha256(content.encode()).hexdigest(),
                prompt=(
                    (decision_ai.ORDER_PROMPT if prior else WEB_ORDER_PROMPT)
                    if user.order_prompt is None
                    else user.order_prompt + decision_ai.CUSTOM_PROMPT_RULES
                )
                + (VERDICT_INSTRUCTION if not prior else "\n판단을 judgment 필드에 명시하세요."),
                prompt_version=VERSION,
                schema=decision_ai.OrderFeedback.model_json_schema() if prior else {},
                output_type="decision" if prior else "quant",
                provider=settings.ai_review_provider,
                requested_model=connected["model"],
                attempt_times=[at.isoformat()],
            ),
        )
        db.add(record)
    else:
        data = copy.deepcopy(record.data)
        data.pop("error", None)
        data["attempt_times"].append(at.isoformat())
        record.data, record.status = data, "pending"
        record.attempts += 1
        record.started_at = record.completed_at = None
    db.flush()
    return status_view(record)


class QuantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: Literal[True]
