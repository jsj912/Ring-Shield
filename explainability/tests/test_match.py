"""XR-28: matching is the research side's own, reproduces its reported counts, and keeps ring ids aligned."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import explainability
from explainability.contract_io import load_config, read_rings, read_scored_edges, repo_path
from explainability.match import (match_in_window, matching_rule, truth_edge_sets, window_from_config,
                                  windowed_prediction_sets)
from explainability.tests import fixtures as fx

CFG = load_config()
SEEDS = [1, 2, 3, 4, 5]


def _need(*paths):
    missing = [p for p in paths if not repo_path(p).exists()]
    if missing:
        pytest.skip(f"files not on disk: {missing}")


def _real(seed):
    scores, rings = (CFG["inputs"][k].format(seed=seed) for k in ("scored_edges", "rings"))
    _need(scores, rings, CFG["inputs"]["truth"], CFG["inputs"]["split_parquet"])
    se = read_scored_edges(scores)
    return se, read_rings(rings, scored_edges=se), rings


@pytest.mark.parametrize("seed", SEEDS)
def test_counts_reproduce_the_research_log(seed):
    """Seed 1 must give 94 predicted / 174 truth / 81 matched; every seed must equal its own run log."""
    se, rings, rings_path = _real(seed)
    log = json.loads(Path(str(repo_path(rings_path)) + ".log.json").read_text(encoding="utf-8"))["primary_window"]
    thr, scope = matching_rule(CFG)
    res = match_in_window(rings, se, window_from_config(CFG), threshold=thr, scope=scope, truth_path=CFG["inputs"]["truth"])
    assert (res.n_pred_in_window, res.n_truth, res.n_matched) == (log["n_predicted"], log["n_truth"], log["n_matched"])
    if seed == 1:
        assert (res.n_pred_in_window, res.n_truth, res.n_matched) == (94, 174, 81)
    assert res.matches["ring_id"].is_unique and res.matches["truth_ring_id"].is_unique   # one-to-one
    assert (res.matches["jaccard"] >= thr).all()


def test_true_edge_sets_agree_with_the_truth_accounts():
    """T (edges, from the split parquet) and the truth account sets (from the ground-truth parquet) must
    describe the same rings: the accounts on T's edges == the truth ring's in-window members."""
    from ringshield.truth import load_ground_truth
    se, rings, _ = _real(1)
    W = window_from_config(CFG)
    thr, scope = matching_rule(CFG)
    res = match_in_window(rings, se, W, threshold=thr, scope=scope, truth_path=CFG["inputs"]["truth"])
    truth, _ = load_ground_truth(repo_path(CFG["inputs"]["truth"]), *W.bounds, scope, verbose=False)
    T = truth_edge_sets(CFG["inputs"]["split_parquet"], W, ring_ids=res.matches["truth_ring_id"])
    for tid in res.matches["truth_ring_id"]:
        assert T.edges[tid], f"truth ring {tid} has no edges in the window"
        assert T.accounts[tid] == truth[tid], f"truth ring {tid}: edge accounts differ from truth members"


def test_a_ring_outside_the_window_does_not_shift_the_ids():
    case = fx.window_shift_case()
    W = window_from_config(CFG)
    ids, sets = windowed_prediction_sets(case["rings"], case["scored_edges"], W)
    assert ids == [fx.PREFIX + "inside_window"]           # the out-of-window ring is dropped, not mislabelled
    res = match_in_window(case["rings"], case["scored_edges"], W, threshold=0.5, scope="test_visible",
                          truth=case["truth"])
    assert res.n_pred_total == 2 and res.n_pred_in_window == 1 and res.n_matched == 1
    assert tuple(res.matches.iloc[0][["ring_id", "truth_ring_id"]]) == case["expected_match"]
    assert res.matches.iloc[0]["jaccard"] == 1.0


def test_no_matching_code_is_reimplemented_in_the_layer():
    """XR-28 by inspection: no function in explainability/ is named like a matcher, and match.py imports
    match_rings from evaluation.ring_metrics."""
    root = Path(explainability.__file__).parent
    forbidden = {"jaccard", "match_rings", "evaluate_rings", "coverage"}
    for py in root.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert not (defined & forbidden), f"{py.name} defines {defined & forbidden}"
    src = (root / "match.py").read_text(encoding="utf-8")
    assert "from evaluation.ring_metrics import match_rings" in src
