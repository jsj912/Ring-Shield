"""Part B2: history is strictly earlier than the scored window; the reserved-seed rule is exact."""
import numpy as np
import pandas as pd
import pytest

from evaluation.history_seeds import DAY, history_set, lifted_scores, reserved_mask


def _illicit():
    # days 0, 5, 6, 7
    return pd.DataFrame({"from_id": [1, 2, 3, 4], "to_id": [10, 20, 30, 40],
                         "Timestamp": [10, 5 * DAY + 1, 6 * DAY + 1, 7 * DAY + 1], "Is Laundering": 1})


def test_val_history_excludes_days_6_onward():
    H = history_set(_illicit(), last_day=5, scored_split_start_ts=6 * DAY)
    assert H == {1, 10, 2, 20}


def test_history_from_inside_window_raises():
    with pytest.raises(ValueError):
        history_set(_illicit(), last_day=7, scored_split_start_ts=6 * DAY)   # day 6-7 labels vs a window starting day 6


def test_test_history_days_0_7_ok():
    assert history_set(_illicit(), last_day=7, scored_split_start_ts=8 * DAY) == {1, 10, 2, 20, 3, 30, 4, 40}


def test_reserved_rule_and_lift_reproduce_topk():
    n = 2000
    rng = np.random.default_rng(0)
    se = pd.DataFrame({"edge_id": np.arange(n), "score_raw": rng.random(n),
                       "from_id": rng.integers(0, 500, n), "to_id": rng.integers(0, 500, n)})
    H = set(range(0, 50))
    m, K = reserved_mask(se, H, 0.5, "one", k_pct=1.0)          # K = 20 at 1 %
    assert K == 20 and m.sum() == 10
    elig = se.from_id.isin(H) | se.to_id.isin(H)
    assert elig[m].all()
    # reserved = top-10 eligible by score
    assert set(se[elig].nlargest(10, "score_raw").edge_id) == set(se.edge_id[m])
    lifted = lifted_scores(se[["edge_id", "score_raw"]], m)
    top = set(lifted.nlargest(K, "score_raw").edge_id)
    rest = se[~m].nlargest(K - 10, "score_raw").edge_id
    assert top == set(se.edge_id[m]) | set(rest)                # reserved + fill by score, no double count
    assert (lifted.score_raw[~m] == se.score_raw[~m]).all()
