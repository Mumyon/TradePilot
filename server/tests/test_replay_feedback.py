from app.services.replay_feedback import breakdown


def check(id, status="hit", decision="deferred", shown=True, allowed=True):
    return dict(
        check_id=id,
        allowed=allowed,
        decision=decision,
        presented_at="recorded" if shown else None,
        shadow=dict(behavior=dict(items=[dict(code="fomo", status=status)])),
    )


def test_rule_breakdown_distinguishes_explicit_deferral_and_order_outcomes():
    state = dict(
        pilot_enabled=True,
        checks=[
            check("defer"),
            check("close", decision="closed"),
            check("expire", decision="expired"),
            check("fill", decision="submitted"),
            check("cancel", decision="submitted"),
            check("block", allowed=False),
            check("hidden", shown=False),
            check("exempt", status="exempt"),
            check("missing", status="unavailable"),
        ],
        orders=[
            dict(check_id="fill", status="filled"),
            dict(check_id="cancel", status="cancelled"),
        ],
    )
    fomo = breakdown(state)[0]
    assert fomo["detected"] == 7 and fomo["presented"] == 5
    assert fomo["deferred_after_presentation"] == 1
    assert fomo["submitted_after_presentation"] == 2
    assert fomo["closed_after_presentation"] == 1
    assert fomo["unresolved_after_presentation"] == 1
    assert fomo["filled"] == 1 and fomo["cancelled"] == 1
    assert fomo["defer_rate"] == 1 / 3
    assert fomo["exempt"] == 1 and fomo["unavailable"] == 1
    assert fomo["blocked"] == 1


def test_off_shadow_detection_does_not_claim_warning_exposure_or_prevention():
    state = dict(pilot_enabled=False, checks=[check("off")], orders=[])
    fomo = breakdown(state)[0]
    assert fomo["detected"] == 1
    assert fomo["presented"] == 0 and fomo["deferred_after_presentation"] == 0
    assert fomo["defer_rate"] is None


def test_no_checks_does_not_make_up_feedback():
    rows = breakdown(dict(pilot_enabled=True, checks=[], orders=[]))
    assert len(rows) == 5
    assert all(row["advice"] is None and row["defer_rate"] is None for row in rows)
