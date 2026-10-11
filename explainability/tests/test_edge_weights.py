"""XR-03 / 04 / 06 / 07: w_score, w_flow, w_loo (+ split), w_total, and the rerun inputs they depend on."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from explainability.contract_io import load_config, read_rings, read_scored_edges, repo_path
from explainability.edge_weights import load_loo_inputs

CFG = load_config()
SEEDS = [1, 2, 3, 4, 5]


def _real(seed, rings_path=None):
    scores = CFG["inputs"]["scored_edges"].format(seed=seed)
    rings_path = rings_path or CFG["inputs"]["rings"].format(seed=seed)
    needed = [scores, rings_path, CFG["research_inputs"]["gfp"], CFG["research_inputs"]["embeddings"].format(seed=seed)]
    if any(not repo_path(p).exists() for p in needed):
        pytest.skip("real contract / research files not on disk")
    se = read_scored_edges(scores)
    return se, read_rings(rings_path, scored_edges=se), rings_path


def _included(ring) -> list[int]:
    return sorted(set(map(int, ring.seed_edges)) | set(map(int, ring.expanded_edges)))


# ----------------------------------------------------------------------------- step 1: rerun inputs
# Rings that do NOT reproduce when rerun on their own (measured 2026-10-11): the shipped run computed the
# affinity features of an account shared between rings over the whole component, the rerun over this ring
# alone (the documented hub/context caveat). 5 of 560 rings. Pinned so any change is caught.
KNOWN_NOT_REPRODUCED = {1: set(), 2: {"full-gine_causal-2-16", "full-gine_causal-2-47", "full-gine_causal-2-105"},
                        3: {"full-gine_causal-3-74"}, 4: {"full-gine_causal-4-90"}, 5: set()}


@pytest.mark.parametrize("seed", SEEDS)
def test_rerun_is_not_degraded_and_reproduces_the_shipped_rings(seed):
    """For every ring: the rerunner gets the real GFP / embeddings / affinity (features_degraded False --
    LooInputs.rerunner raises otherwise). Every ring outside the pinned set regroups to exactly itself and
    its confidence c0 equals the shipped `confidence`; the rings that do not are exactly the pinned set."""
    se, rings, rings_path = _real(seed)
    ids = [e for r in rings.itertuples() for e in _included(r)]
    inp = load_loo_inputs(CFG, seed, "full", rings_path, ids)
    assert (inp.min_size, inp.cut, inp.method) == (3, 0.5, "average")
    sei = se.set_index("edge_id")
    not_reproduced = set()
    for r in rings.itertuples(index=False):
        rr = inp.rerunner(sei.loc[_included(r)].reset_index())
        assert rr.features_degraded is False
        out = rr.run()
        c0, shipped = out["confidence"], r.confidence
        same = out["n_rings"] == 1 and out["largest_ring_edges"] == _included(r) and (
            (math.isnan(c0) and math.isnan(shipped)) or abs(c0 - shipped) < 1e-9)
        if not same:
            not_reproduced.add(r.ring_id)
    assert not_reproduced == KNOWN_NOT_REPRODUCED[seed]


# ----------------------------------------------------------------------------- step 2: Week 2 fixtures
@pytest.mark.parametrize("case", ["loo_case", "roles_case"])
def test_week2_contract_fixtures_validate(case):
    from explainability.contract_io import validate_rings, validate_scored_edges
    from explainability.tests import fixtures as fx
    c = getattr(fx, case)()
    validate_scored_edges(c["scored_edges"], f"{case} scored_edges")
    validate_rings(c["rings"], c["scored_edges"], what=f"{case} rings")


# ----------------------------------------------------------------------------- step 3: w_flow
def test_w_flow_counts_a_duplicate_payment_once():
    from explainability.edge_weights import w_flow
    from explainability.tests import fixtures as fx
    c = fx.flow_case()
    got = w_flow(c["edges"], "amount_received")
    for e, v in c["w_flow"].items():
        assert abs(got.loc[e] - v) < 1e-12


def test_w_flow_matches_the_hand_computation():
    from explainability.edge_weights import w_flow
    from explainability.tests import fixtures as fx
    c = fx.loo_case()
    got = w_flow(c["scored_edges"].loc[c["scored_edges"]["edge_id"].isin(c["ids"].values())], "amount_received")
    for name, eid in c["ids"].items():
        assert abs(got.loc[eid] - c["w_flow"][name]) < 1e-6
    assert abs(got.sum() - 1.0) < 1e-12


def test_w_flow_is_zero_when_the_ring_moves_no_money():
    from explainability.edge_weights import w_flow
    e = pd.DataFrame({"edge_id": [1, 2], "from_id": [1, 2], "to_id": [2, 3], "timestamp": [1, 2], "amount_received": [0.0, 0.0]})
    assert (w_flow(e) == 0).all()


# ----------------------------------------------------------------------------- step 4: w_loo + split
def _cc_inputs():
    from explainability.edge_weights import LooInputs
    return LooInputs("cc", 3)


def _included_frame(c):
    se, ring = c["scored_edges"], c["rings"].iloc[0]
    inc = set(ring.seed_edges) | set(ring.expanded_edges)
    return se[se["edge_id"].isin(inc)].reset_index(drop=True)


def _mini(rows):
    """Tiny edge frame for the rerunner: (edge_id, from, to, hour, amount, score, is_seed)."""
    return pd.DataFrame([{"edge_id": e, "from_id": f, "to_id": t, "timestamp": 700000 + int(h * 3600),
                          "amount_received": float(a), "score_calibrated": s, "score_raw": s, "is_seed": sd}
                         for e, f, t, h, a, s, sd in rows])


def test_w_loo_matches_the_hand_computation():
    from explainability.edge_weights import w_loo
    from explainability.tests import fixtures as fx
    c = fx.loo_case()
    t = w_loo(_included_frame(c), _cc_inputs().rerunner, lambda_split=0.5).set_index("edge_id")
    name_of = {v: k for k, v in c["ids"].items()}
    assert len(t) == 4                                             # e5 is not included -> not rerun
    for eid, row in t.iterrows():
        n = name_of[eid]
        assert abs(row.c0 - c["c0"]) < 1e-6
        assert abs(row.c_minus - c["c_minus"][n]) < 1e-6, n
        assert row.split == c["split"][n], n
        assert abs(row.w_loo - c["w_loo"][n]) < 1e-6, n


def test_split_flags_mark_bridges_only():
    from explainability.edge_weights import split_flags
    from explainability.tests import fixtures as fx
    se, rings = fx.fixture_contract()
    sei = se.set_index("edge_id")
    by_id = rings.set_index("ring_id")
    stack = sei.loc[by_id.at[fx.PREFIX + "stack", "member_edges"]].reset_index()           # a chain: every link is a bridge
    assert split_flags(stack).tolist() == [1, 1, 1, 1]
    loop = sei.loc[by_id.at[fx.PREFIX + "nan_closure_cycle", "member_edges"]].reset_index()  # a loop: no link is a bridge
    assert split_flags(loop).tolist() == [0, 0, 0]


def test_rerunner_is_called_exactly_edges_plus_one_times():
    """XR-06: one call for c0, one per included edge, nothing else."""
    from explainability.edge_weights import w_loo
    from explainability.tests import fixtures as fx
    calls = {"run": 0, "without": 0, "built": 0}

    class Spy:
        def __init__(self, rr):
            self.rr = rr

        def run(self, *a, **k):
            calls["run"] += 1
            return self.rr.run(*a, **k)

        def without(self, e):
            calls["without"] += 1
            return self.rr.without(e)

    def factory(edges):
        calls["built"] += 1
        return Spy(_cc_inputs().rerunner(edges))
    edges = _included_frame(fx.loo_case())
    w_loo(edges, factory, lambda_split=0.5)
    assert calls == {"built": 1, "run": 1, "without": len(edges)}
    assert calls["run"] + calls["without"] == len(edges) + 1


def test_a_ring_that_disappears_without_an_edge_counts_as_full_loss():
    """2 edges, 3 accounts: removing either leaves 2 accounts (< min_size 3) -> no ring (NaN) -> drop = c0."""
    from explainability.edge_weights import w_loo
    t = w_loo(_mini([(1, 10, 11, 0, 100, 0.9, True), (2, 11, 12, 1, 95, 0.8, True)]), _cc_inputs().rerunner, lambda_split=0.5)
    assert t["c_minus"].isna().all()
    assert (abs(t["drop"] - t["c0"]) < 1e-12).all()
    assert (t["split"] == 1).all() and (t["w_loo"] == 1.0).all()


def test_all_zero_weights_when_nothing_matters():
    """A 3-edge loop with equal amounts and scores: removing any edge keeps one connected chain (no split)
    whose confidence equals c0 (0.9 x closure 1 vs 0.9 with no closure) -> every raw value 0 -> w_loo 0."""
    from explainability.edge_weights import w_loo
    t = w_loo(_mini([(1, 10, 11, 0, 100, 0.9, True), (2, 11, 12, 1, 100, 0.9, True), (3, 12, 10, 2, 100, 0.9, True)]),
              _cc_inputs().rerunner, lambda_split=0.5)
    assert (t["split"] == 0).all() and (t["drop"].abs() < 1e-12).all() and (t["w_loo"] == 0).all()


def test_unknown_nan_policy_is_refused():
    from explainability.edge_weights import w_loo
    with pytest.raises(ValueError, match="loo_nan_policy"):
        w_loo(_mini([(1, 10, 11, 0, 1, 0.9, True)]), _cc_inputs().rerunner, lambda_split=0.5, nan_policy="ignore")


# ----------------------------------------------------------------------------- step 5: w_total
def _table(mixing):
    from explainability.edge_weights import edge_weight_table, w_loo
    from explainability.tests import fixtures as fx
    c = fx.loo_case()
    loo = w_loo(_included_frame(c), _cc_inputs().rerunner, lambda_split=0.5)
    return c, edge_weight_table(c["scored_edges"], loo, mixing)


def test_w_total_matches_the_hand_computation_for_all_five_edges():
    """XR-03: the 5-edge ring, every component and the total, to 1e-6; sorted by w_total."""
    c, t = _table(CFG["edge_weights"]["mixing_default"])
    name_of = {v: k for k, v in c["ids"].items()}
    assert len(t) == 5 and list(t.columns[:5]) == ["edge_id", "w_total", "w_score", "w_loo", "w_flow"]
    for row in t.itertuples(index=False):
        n = name_of[row.edge_id]
        for col in ("w_total", "w_score", "w_loo", "w_flow"):
            assert abs(getattr(row, col) - c[col][n]) < 1e-6, (n, col)
    assert [name_of[e] for e in t["edge_id"]] == c["order"]
    e5 = t[t["edge_id"] == c["ids"]["e5"]].iloc[0]
    assert e5.w_loo == 0 and e5.split == 0 and not e5.included   # member-only edge: grouping never used it


def test_changing_the_mixing_weights_changes_the_output():
    """XR-04: weights come from config; a different (alpha, beta, gamma) gives a different table."""
    _, base = _table({"alpha": 0.4, "beta": 0.4, "gamma": 0.2})
    _, score_only = _table({"alpha": 1.0, "beta": 0.0, "gamma": 0.0})
    assert not base["w_total"].equals(score_only["w_total"])
    assert (score_only.set_index("edge_id")["w_total"] == score_only.set_index("edge_id")["w_score"]).all()


@pytest.mark.parametrize("bad", [{"alpha": 0.5, "beta": 0.5, "gamma": 0.5}, {"alpha": 1.2, "beta": -0.2, "gamma": 0.0}])
def test_invalid_mixing_weights_are_refused(bad):
    with pytest.raises(ValueError, match="mixing weights"):
        _table(bad)


def test_missing_rerun_inputs_are_refused():
    """A `full` rerunner without GFP / embeddings would be degraded; LooInputs refuses to build it."""
    from explainability.edge_weights import LooInputs
    se, rings, rings_path = _real(1)
    r = next(rings.itertuples(index=False))
    inp = load_loo_inputs(CFG, 1, "full", rings_path, _included(r))
    inp.emb = None
    with pytest.raises(RuntimeError, match="features_degraded"):
        inp.rerunner(se.set_index("edge_id").loc[_included(r)].reset_index())
