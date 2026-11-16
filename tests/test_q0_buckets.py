from evaluation.q0_loss_decomposition import assign, classify_c

V = {1, 2, 3, 4, 5, 6}


def test_a_precedence_and_flag():
    r = assign(V, has_ge3_piece=False, matched=True, seed_touched=True, preds=[], matched_preds=set(),
               other_ring_accounts=set())
    assert r == {"bucket": "a", "a_matched": True}


def test_d_then_b():
    assert assign(V, True, True, False, [], set(), set())["bucket"] == "d"
    assert assign(V, True, False, False, [], set(), set())["bucket"] == "b"


def test_c1_no_prediction():
    r = classify_c(V, [{10, 11, 12}], set(), set())
    assert r["bucket"] == "c1" and r["c1_no_prediction"]


def test_c1_too_few():
    r = classify_c(V, [{1, 2, 3}], set(), set())         # J = 0.5? 3/6 -> matched elsewhere; use 2 members
    r = classify_c(V, [{1, 2, 99}], set(), set())        # 1 outsider, 4 missing
    assert r["bucket"] == "c1" and not r["c1_no_prediction"]


def test_c2_merged_with_other_ring_and_noise():
    big = {1, 2, 3, 20, 21, 22, 23}                     # 4 outsiders > 3 missing
    r = classify_c(V, [big], set(), other_ring_accounts={20})
    assert r["bucket"] == "c2" and r["c2_other_ring"]
    r = classify_c(V, [big], set(), other_ring_accounts=set())
    assert r["bucket"] == "c2" and not r["c2_other_ring"]


def test_c2_one_to_one():
    P = {1, 2, 3, 4, 5, 30}                              # J = 5/7 >= 0.5 but used by another ring
    r = classify_c(V, [P], matched_preds={0}, other_ring_accounts={30})
    assert r["bucket"] == "c2" and r["c2_one_to_one"]


def test_c3_split():
    r = classify_c(V, [{1, 2}, {3, 4}], set(), set())    # two fragments, 4/6 covered
    assert r["bucket"] == "c3"


def test_two_fragments_too_small_is_not_c3():
    W = set(range(1, 13))
    r = classify_c(W, [{1, 2}, {3, 4}], set(), set())    # 4/12 < half -> c1
    assert r["bucket"] == "c1"


def test_tie_outsiders_equal_missing_is_c1():
    r = classify_c(V, [{1, 2, 3, 40, 41, 42}], set(), set())   # 3 outsiders == 3 missing
    assert r["bucket"] == "c1"
