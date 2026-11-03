"""Frozen prediction review must not introduce lookahead or inflate denominators."""

import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.replay_predictions import review


def fixture(direction="up", future=10100, cursor=12):
    opening = datetime(2024, 8, 5, 3, tzinfo=UTC)
    case = SimpleNamespace(
        rows=[
            dict(
                opened_at=(opening + timedelta(minutes=5 * i)).isoformat(),
                close_won=future if i == 12 else 10000,
            )
            for i in range(15)
        ]
    )
    check = dict(
        check_id="first",
        analysis=dict(
            prediction=dict(
                status="available",
                direction=direction,
                model_version="frozen-v1",
                as_of=(opening + timedelta(minutes=5)).isoformat(),
                probabilities=dict(up=0.8, neutral=0.1, down=0.1),
            )
        ),
    )
    return case, dict(cursor=cursor, checks=[check])


@pytest.mark.parametrize(
    "future,actual", [(10050, "neutral"), (9950, "neutral"), (10051, "up"), (9949, "down")]
)
def test_exact_threshold_and_twelve_bar_horizon(future, actual):
    case, state = fixture(future=future)
    result = review(case, state)
    outcome = result["observations"][0]["outcome"]
    assert outcome["actual_direction"] == actual
    assert outcome["target_price_won"] == future
    assert outcome["correct"] == (actual == "up")
    assert result["summary"]["evaluated"] == 1


def test_hidden_future_is_not_scored_after_early_finish():
    case, state = fixture(cursor=11)
    state["finished"] = True
    expected = review(case, state)
    case.rows[12]["close_won"] = 1
    assert review(case, state) == expected
    assert expected["summary"]["pending"] == 1
    assert expected["summary"]["accuracy"] is None
    assert "target_price_won" not in expected["observations"][0]["outcome"]


@pytest.mark.parametrize("missing", [6, 12])
def test_missing_interior_or_target_bar_not_replaced_with_next_observation(missing):
    case, state = fixture(cursor=13)
    del case.rows[missing]
    result = review(case, state)
    assert result["summary"]["unavailable"] == 1
    assert result["summary"]["evaluated"] == 0


def test_abstention_and_repeated_checks_do_not_inflate_accuracy():
    case, state = fixture(direction="abstain")
    second = copy.deepcopy(state["checks"][0])
    second["check_id"] = "repeat"
    state["checks"].extend([second, dict(check_id="none", analysis={})])
    original = copy.deepcopy(state)
    result = review(case, state)
    assert state == original
    assert result["summary"] == dict(
        unique_predictions=1,
        unavailable_checks=1,
        resolved=1,
        pending=0,
        unavailable=0,
        abstained=1,
        evaluated=0,
        correct=0,
        accuracy=None,
    )
    assert result["observations"][0]["check_ids"] == ["first", "repeat"]


def test_no_checks_is_not_zero_percent_accuracy():
    case, state = fixture()
    state["checks"] = []
    assert review(case, state)["summary"]["accuracy"] is None
