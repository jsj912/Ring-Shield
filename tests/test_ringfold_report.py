"""T-P2 report helpers on hand-built fixtures (three rings)."""
import pandas as pd
import pytest

from evaluation.ringfold_report import assert_ring_folds, jaccard, overlap_shares


def test_overlap_shares_three_rings():
    shipped = [{1, 2, 3}, {4, 5, 6, 7}, {8, 9, 10}]
    other = [{1, 2, 3}, {4, 5, 6}, {11, 12, 13}]      # exact; J=0.75; disjoint
    o = overlap_shares(shipped, other)
    assert o["n_exact"] == 1 and o["exact_share"] == pytest.approx(1 / 3)
    assert o["n_jaccard"] == 2 and o["jaccard_share"] == pytest.approx(2 / 3)
    assert jaccard({4, 5, 6, 7}, {4, 5, 6}) == pytest.approx(0.75)


def test_overlap_is_one_to_one():
    # two copies of a shipped ring can be matched to only one ringfold prediction
    o = overlap_shares([{1, 2, 3}, {1, 2, 3}], [{1, 2, 3}])
    assert o["n_exact"] == 2 and o["n_jaccard"] == 1


def test_ring_fold_assertion():
    rf = pd.DataFrame({"edge_id": [1, 2, 3, 4], "ring_id": [7, 7, 8, 8], "fold": [0, 0, 2, 2]})
    ok = pd.DataFrame({"edge_id": [1, 2, 3, 4, 5], "fold": [0, 0, 2, 2, 1]})
    assert assert_ring_folds(rf, ok)["passed"]
    leak = ok.assign(fold=[0, 1, 2, 2, 1])            # edge 2 of ring 7 scored by another fold
    with pytest.raises(AssertionError):
        assert_ring_folds(rf, leak)
