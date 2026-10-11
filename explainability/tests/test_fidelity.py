"""XR-22 / XR-24 (Week 1): the fidelity metric, the score-only ranking, the random control, determinism."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from explainability import evaluate
from explainability.contract_io import load_config, repo_path
from explainability.edge_weights import rank_by_score, w_score
from explainability.evaluate import evaluate_frames, fidelity_at_k, random_fidelity
from explainability.match import TruthEdges, match_in_window, window_from_config
from explainability.tests import fixtures as fx

CFG = load_config()


# ----------------------------------------------------------------------------- hand-computed case
def test_five_edge_ring_matches_the_hand_computation():
    case = fx.five_edge_case()
    ranked = rank_by_score(case["edges"])
    assert ranked == case["ranking"]
    for k, expected in case["fidelity"].items():
        assert abs(fidelity_at_k(ranked, case["truth"], k) - expected) < 1e-9


def test_w_score_is_the_calibrated_score():
    case = fx.five_edge_case()
    w = w_score(case["edges"])
    assert w.loc[11] == 0.90 and w.loc[15] == 0.10 and len(w) == 5


def test_ties_break_on_raw_score_then_edge_id_and_missing_scores_go_last():
    edges = pd.DataFrame({"edge_id": [5, 3, 9, 1, 7],
                          "score_calibrated": [0.5, 0.5, 0.5, float("nan"), 0.9],
                          "score_raw": [0.6, 0.6, 0.7, 0.99, 0.95]})
    # 7 (0.9) first; then the 0.5 tie: 9 (raw 0.7) before 3 and 5 (raw 0.6 tie -> lower edge_id first); NaN last
    assert rank_by_score(edges) == [7, 9, 3, 5, 1]


def test_fidelity_edge_cases():
    assert fidelity_at_k([1, 2], {1, 2, 3, 4}, 3) == 2 / 3      # fewer edges than k: denominator min(k, |T|)
    assert fidelity_at_k([1, 2, 3], {9}, 3) == 0.0
    assert fidelity_at_k([9, 1, 2], {9}, 3) == 1.0               # |T| = 1: denominator 1
    with pytest.raises(ValueError):
        fidelity_at_k([1], set(), 3)


# ----------------------------------------------------------------------------- the random control
def test_random_control_is_reproducible_under_its_seed():
    ids, T = list(range(40)), set(range(0, 40, 3))
    a = random_fidelity(ids, T, [3, 5, 10], 20, [20260921, 1, 0])
    b = random_fidelity(list(reversed(ids)), T, [3, 5, 10], 20, [20260921, 1, 0])   # input order must not matter
    assert a == b
    assert random_fidelity(ids, T, [3, 5, 10], 20, [20260921, 1, 1]) != a          # a different ring gets other shuffles


def test_random_control_converges_to_its_expected_value():
    """For a random order, E[|top-k & T|] = k * |T| / n, so E[fidelity@k] = (k * |T| / n) / min(k, |T|)."""
    n, T = 30, set(range(10))
    got = random_fidelity(list(range(n)), T, [3, 5, 10], 4000, [7])
    for k in (3, 5, 10):
        assert abs(got[k] - (k * len(T) / n) / min(k, len(T))) < 0.02


# ----------------------------------------------------------------------------- on the fixtures
def test_every_fixture_ring_scores_one_when_all_its_edges_are_true():
    """Sanity: match each fixture ring against itself; T = all its edges, so every ranking scores 1.0."""
    se, rings = fx.fixture_contract()
    W = window_from_config(CFG)
    truth = {i + 1: set(m) for i, m in enumerate(rings["members"])}
    res = match_in_window(rings, se, W, threshold=0.5, scope="test_visible", truth=truth)
    assert res.n_matched == len(rings)
    edges_of = {i + 1: set(e) for i, e in enumerate(rings["member_edges"])}
    T = TruthEdges(edges={int(t): edges_of[int(t)] for t in res.matches["truth_ring_id"]}, accounts={})
    per_ring, summary = evaluate_frames(se, rings, res, T, W, CFG, detector_seed=0)
    assert len(per_ring) == len(rings)
    for name in ("score_only", "random"):
        for k in ("3", "5", "10"):
            assert math.isclose(summary[name][k], 1.0)


# ----------------------------------------------------------------------------- determinism on real data
def test_two_runs_write_byte_identical_json(tmp_path):
    inp = CFG["inputs"]
    needed = [inp["scored_edges"].format(seed=1), inp["rings"].format(seed=1), inp["truth"], inp["split_parquet"]]
    if any(not repo_path(p).exists() for p in needed):
        pytest.skip("real contract files not on disk")
    for run in ("a", "b"):
        assert evaluate.main(["--seeds", "1", "--out", str(tmp_path / run)]) == 0
    a = (tmp_path / "a" / "fidelity_week1_seed1.json").read_bytes()
    b = (tmp_path / "b" / "fidelity_week1_seed1.json").read_bytes()
    assert a == b and len(a) > 1000
