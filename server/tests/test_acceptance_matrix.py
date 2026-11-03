"""Independent labeled behavior scenarios; labels are rule expectations, not human emotions."""

from datetime import timedelta

import pytest
from test_risk import check, history, item, plan, quotes

from app.models import Order, now

CASES = [
    ("fomo", "normal", False),
    ("fomo", "boundary", True),
    ("fomo", "risk", True),
    ("fomo", "plan", False),
    ("panic", "normal", False),
    ("panic", "boundary", True),
    ("panic", "risk", True),
    ("panic", "plan", False),
    ("revenge", "normal", False),
    ("revenge", "recent", True),
    ("revenge", "expired", False),
    ("revenge", "plan", False),
    ("overtrading", "normal", False),
    ("overtrading", "boundary", True),
    ("overtrading", "risk", True),
    ("overtrading", "plan", False),
]


@pytest.mark.parametrize("code,case,expected", CASES)
def test_labeled_behavior_scenario(service, code, case, expected, record_property):
    price = 100000
    side = "sell" if code == "panic" else "buy"
    selected = None
    if code == "fomo":
        price = {"normal": 102999, "boundary": 103000, "risk": 105000, "plan": 105000}[case]
    if code == "panic":
        price = {"normal": 97001, "boundary": 97000, "risk": 95000, "plan": 95000}[case]
    client = quotes(service, current=price)
    if case == "plan":
        selected = plan(
            service,
            side=side,
            minutes=60,
            split_order=True,
            stop_loss_won=96000 if side == "sell" else None,
        )
    if code == "revenge":
        history(
            service,
            [-100, 100, -100] if case == "normal" else [-100] * 3,
            minutes=31 if case == "expired" else 5,
        )
    if code == "overtrading":
        _, sessions, uid, _ = service
        count = 3 if case == "normal" else 5 if case == "risk" else 4
        with sessions.begin() as db:
            for n in range(count):
                db.add(
                    Order(
                        user_id=uid,
                        symbol="005930",
                        side="buy",
                        quantity=1,
                        limit_price_won=100000,
                        status="cancelled",
                        request_body={},
                        idempotency_key=f"matrix-{n}",
                        plan_group_id=selected,
                        created_at=now() - timedelta(minutes=10),
                    )
                )
    _, result = check(client, side=side, plan_id=selected)
    observed = item(result, code)["status"] == "hit"
    record_property("behavior_code", code)
    record_property("expected_warning", str(expected))
    record_property("observed_warning", str(observed))
    assert observed == expected
