"""Toss paper execution uses the exchange's continuous regular session only."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..models import MarketCalendar, now

KST = ZoneInfo("Asia/Seoul")


def refresh(db, provider, settings):
    if settings.market_data_mode != "toss":
        return
    at = now()
    cached = db.get(MarketCalendar, "toss_kr")
    if cached and timedelta(0) <= at - cached.checked_at < timedelta(seconds=60):
        return
    try:
        payload = provider.get_market_calendar()
    except Exception:
        return  # Last verified calendar is usable for five minutes only.
    if cached is None:
        cached = MarketCalendar(source="toss_kr", payload=payload, checked_at=at)
        db.add(cached)
    else:
        cached.payload, cached.checked_at = payload, at


def status(db, settings, at=None):
    at = at or now()
    if settings.market_data_mode != "toss":
        return dict(state="unrestricted", can_trade=True, message="모의 체결 정책 적용")
    row = db.get(MarketCalendar, "toss_kr")
    unavailable = dict(
        state="unavailable",
        can_trade=False,
        message="거래 시간 확인 중입니다. 확인 후 주문할 수 있습니다.",
    )
    if not row or not timedelta(0) <= at - row.checked_at <= timedelta(minutes=5):
        return unavailable
    try:
        day = row.payload["today"]
        if day["date"] != at.astimezone(KST).date().isoformat():
            return unavailable
        integrated = day.get("integrated") or {}
        if not isinstance(integrated, dict):
            return unavailable
        session = integrated.get("regularMarket")
        if not session:
            return dict(
                state="closed",
                can_trade=False,
                message="오늘은 정규 거래일이 아닙니다.",
                checked_at=row.checked_at,
            )
        start = datetime.fromisoformat(session["startTime"])
        end = datetime.fromisoformat(session["singlePriceAuctionStartTime"])
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            return unavailable
        if any(bound.astimezone(KST).date() != at.astimezone(KST).date() for bound in (start, end)):
            return unavailable
    except (KeyError, TypeError, ValueError):
        return unavailable
    opened = start <= at < end
    return dict(
        state="open" if opened else "closed",
        can_trade=opened,
        message="정규장 모의주문 가능"
        if opened
        else "정규장 연속매매 시간 외에는 주문·체결하지 않습니다.",
        opens_at=start,
        closes_at=end,
        checked_at=row.checked_at,
    )


def test_mode_available(db, settings):
    at = now()
    local = at.astimezone(KST)
    if settings.paper_test_date != local.date() or settings.orders_halted:
        return False
    session = status(db, settings, at)
    opens_at = session.get("opens_at")
    return at < opens_at if opens_at else local.time() < time(9)


def execution_allowed(db, settings, quote_at):
    current = status(db, settings)
    if not current["can_trade"]:
        return False, current["message"]
    if current["state"] == "open" and not current["opens_at"] <= quote_at < current["closes_at"]:
        return False, "정규장 체결 시세를 기다리는 중입니다."
    return True, ""


def expired(db, settings, created_at):
    if settings.market_data_mode != "toss":
        return False
    at = now()
    if created_at.astimezone(KST).date() < at.astimezone(KST).date():
        return True
    current = status(db, settings, at)
    return current.get("closes_at") is not None and at >= current["closes_at"]
