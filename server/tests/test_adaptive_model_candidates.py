from copy import deepcopy
from datetime import datetime, timedelta

import numpy as np

from app.ml.pipeline import KST
from tool.compare_market_context import adaptive_candidates, adaptive_prior


def test_adaptive_prior_uses_only_already_closed_outcomes():
    start = datetime(2025, 1, 2, 9, tzinfo=KST)
    rows = [
        dict(
            as_of=start + timedelta(minutes=5 * i),
            target_at=start + timedelta(minutes=5 * i + 60),
            y=i % 3,
        )
        for i in range(40)
    ]
    prior = [0.2, 0.5, 0.3]
    origins = [10, 12, 15]
    before = adaptive_prior(rows, origins, prior)
    np.testing.assert_allclose(before[0], prior)
    np.testing.assert_allclose(before[1], (30 * np.array(prior) + [1, 0, 0]) / 31)

    changed = deepcopy(rows)
    for row in changed:
        if row["target_at"] > rows[origins[-1]]["as_of"]:
            row["y"] = (row["y"] + 1) % 3
    np.testing.assert_array_equal(adaptive_prior(changed, origins, prior), before)

    forecasts = {
        name: np.tile(prior, (len(origins), 1))
        for name in (
            "cross-stock-logistic",
            "cross-stock-catboost",
            "student-t-return-regression",
        )
    }
    candidates = adaptive_candidates(rows, [], origins, prior, forecasts)
    changed_candidates = adaptive_candidates(changed, [], origins, prior, forecasts)
    assert len(candidates) == 4
    for name, probabilities in candidates.items():
        np.testing.assert_array_equal(probabilities, changed_candidates[name])
        np.testing.assert_allclose(probabilities.sum(axis=1), 1)
        assert np.isfinite(probabilities).all()
        assert np.all((probabilities >= 0) & (probabilities <= 1))
