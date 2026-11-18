"""Order independence of the ring matcher (results/notes/matcher_tiebreak.md).

Equal-Jaccard case: truth 1 = {a,b,c}, truth 2 = {a,b,x}; predictions P = {a,b}, Q = {a,c}.
J(P,1) = J(Q,1) = J(P,2) = 2/3. The shipped rule ("file_order") matches 1 pair if P is listed
first and 2 pairs if Q is listed first. The opt-in "deterministic" rule gives the same result
in both orders. The file-order test is marked xfail (strict): it documents the dependence and
fails loudly if the default ever becomes order independent without this note being updated.
"""
import pytest

from evaluation.ring_metrics import match_rings

TRUTH = {1: {"a", "b", "c"}, 2: {"a", "b", "x"}}
P, Q = {"a", "b"}, {"a", "c"}


def _matched(order, tie_break):
    m, _, _ = match_rings(order, TRUTH, threshold=0.5, tie_break=tie_break)
    return sorted((frozenset(order[r.pred_idx]), r.truth_id) for r in m)


@pytest.mark.xfail(strict=True, reason="shipped file-order rule depends on ring order (default kept pending author decision)")
def test_file_order_is_order_independent():
    assert _matched([P, Q], "file_order") == _matched([Q, P], "file_order")


def test_deterministic_is_order_independent():
    assert _matched([P, Q], "deterministic") == _matched([Q, P], "deterministic")


def test_default_unchanged():
    m, _, _ = match_rings([P, Q], TRUTH)
    assert [(r.pred_idx, r.truth_id) for r in m] == [(0, 1)]


def test_unknown_rule_rejected():
    with pytest.raises(ValueError):
        match_rings([P], TRUTH, tie_break="random")
