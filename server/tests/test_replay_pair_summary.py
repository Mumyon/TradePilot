import copy

import pytest

from app.services.replay import digest
from tool.replay_pair_summary import summarize_exports


def pair(participant="test-person", pair_id="test-pair", on_plan="clear", kind="synthetic"):
    rows = [
        dict(opened_at=f"2024-08-05T03:{minute}:00+00:00", close_won=10000)
        for minute in ("00", "05")
    ]
    case = dict(data_sha256=digest(rows), data_kind=kind)
    documents = []
    for sequence in (1, 2):
        enabled = sequence == 1
        run_id = f"{pair_id}-{sequence}"
        state = dict(
            pair_id=pair_id,
            sequence=sequence,
            pilot_enabled=enabled,
            finished=True,
            paired_run_id=None if enabled else f"{pair_id}-1",
            cursor=1,
            comparison_key="test-comparison",
            config=dict(initial_cash_won=10000000),
            plan=dict(side="buy"),
            behavior_policy=dict(version="test-only"),
            allocation_method="server_randomized",
            condition_order=["ON", "OFF"],
            allocation_at="2026-11-01T00:00:00Z",
            cash=10000000,
            quantity=0,
            equity=[dict(value=10000000)],
            checks=[],
            orders=[
                dict(
                    check_id="test-check",
                    status="filled",
                    analysis=dict(context=dict(plan_status=on_plan if enabled else "hit")),
                )
            ],
        )
        documents.append(
            dict(
                participant_id=participant,
                run_id=run_id,
                case=case,
                case_rows=rows,
                model=None,
                state=state,
                summary=dict(plan_compliance_rate=999),
            )
        )
    return documents


def test_synthetic_excluded_by_default_and_recomputed_when_explicitly_enabled():
    docs = pair()
    assert not summarize_exports(docs)["pairs"]
    result = summarize_exports(docs + [docs[0]], include_synthetic=True)
    assert result["duplicate_files_ignored"] == 1
    assert result["pairs"][0]["plan_compliance_difference_pp"] == 100
    assert result["cohorts"][0]["participants"] == 1


@pytest.mark.parametrize("change", ["cursor", "model", "policy", "condition", "incomplete"])
def test_incomparable_or_incomplete_pairs_are_excluded(change):
    docs = copy.deepcopy(pair())
    if change == "cursor":
        docs[1]["state"]["cursor"] = 0
    elif change == "model":
        docs[1]["model"] = dict(version="changed")
    elif change == "policy":
        docs[1]["state"]["behavior_policy"] = dict(version="changed")
    elif change == "condition":
        docs[1]["state"]["pilot_enabled"] = True
    else:
        docs.pop()
    result = summarize_exports(docs, include_synthetic=True)
    assert not result["pairs"] and len(result["excluded"]) == 1


def test_conflicting_exports_and_modified_ohlcv_are_not_silently_accepted():
    docs = pair()
    duplicate = copy.deepcopy(docs[0])
    duplicate["state"]["cash"] += 100
    with pytest.raises(ValueError, match="서로 다른"):
        summarize_exports([docs[0], duplicate])
    docs = copy.deepcopy(pair())
    docs[0]["case_rows"][0]["close_won"] += 1
    with pytest.raises(ValueError, match="해시"):
        summarize_exports(docs)


def test_participants_are_equal_weighted_instead_of_pooling_repeated_checks():
    docs = pair("a", "a1") + pair("a", "a2", on_plan="hit") + pair("b", "b1")
    result = summarize_exports(docs, include_synthetic=True)
    assert result["cohorts"][0]["mean_participant_plan_difference_pp"] == 75
    assert result["cohorts"][0]["participants_with_plan_comparison"] == 2


def test_unregistered_plan_denominator_stays_null():
    docs = pair(on_plan="unregistered")
    result = summarize_exports(docs, include_synthetic=True)
    assert result["pairs"][0]["plan_compliance_difference_pp"] is None
    assert result["cohorts"][0]["mean_participant_plan_difference_pp"] is None


def test_historical_and_practice_cohorts_never_pool():
    docs = pair(pair_id="practice") + pair(pair_id="historical", kind="historical")
    result = summarize_exports(docs, include_synthetic=True)
    assert {g["data_kind"] for g in result["cohorts"]} == {"synthetic", "historical"}
