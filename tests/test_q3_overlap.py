from evaluation.q3_overlap import analyse, feasible, max_simultaneous


def test_disjoint_rings_all_matchable():
    r = analyse({1: {1, 2, 3}, 2: {4, 5, 6}})
    assert r["accounts_in_gt1_ring"] == 0 and r["max_matchable_m"] == 2 and r["ceiling_ring_f1"] == 1.0


def test_small_overlap_still_both():
    # share one account; each keeps >= half on its own side
    assert feasible([{1, 2, 3}, {3, 4, 5}])


def test_heavy_overlap_only_one():
    # {1,2} and {1,2,3}: need 1 + 2 disjoint accounts out of 3 -> feasible; {1,2},{1,2}: need 1+1 of 2 -> feasible
    assert feasible([{1, 2}, {1, 2}])
    # three copies of a 2-set need 3 accounts out of 2 -> only 2 matchable
    assert max_simultaneous([{1, 2}, {1, 2}, {1, 2}]) == 2


def test_ceiling_formula():
    r = analyse({1: {1, 2}, 2: {1, 2}, 3: {1, 2}, 4: {7, 8, 9}})
    assert r["max_matchable_m"] == 3 and abs(r["ceiling_ring_f1"] - 6 / 7) < 1e-12
