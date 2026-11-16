from evaluation.q6_rescue import rescued_rings

ENDS = {1: (10, 11), 2: (11, 12), 3: (12, 13), 4: (20, 21), 5: (21, 99)}


def g(seeds, adds):
    return {"seeds": seeds, "adds": [(e, p, 0.0, False) for e, p in adds], "stop": "below_p_floor"}


def test_prefix_by_p_min():
    groups = [g([1], [(2, 0.6), (3, 0.2)])]
    assert rescued_rings(groups, set(), ENDS, 0.7) == []                       # stops before 0.6
    r = rescued_rings(groups, set(), ENDS, 0.5)
    assert r[0]["members"] == {10, 11, 12}
    r = rescued_rings(groups, set(), ENDS, 0.1)
    assert r[0]["members"] == {10, 11, 12, 13}


def test_edges_touching_big_groups_dropped():
    groups = [g([4], [(5, 0.9)])]
    assert rescued_rings(groups, {99}, ENDS, 0.5) == []                        # 5 touches a shipped account
    assert rescued_rings(groups, set(), ENDS, 0.5)[0]["members"] == {20, 21, 99}


def test_two_small_groups_merge():
    groups = [g([1], []), g([2], [])]
    r = rescued_rings(groups, set(), ENDS, 0.7)
    assert len(r) == 1 and r[0]["members"] == {10, 11, 12}
