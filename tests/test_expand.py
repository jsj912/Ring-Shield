"""Step 6 -- expansion: index, candidates, features, cross-scoring folds, dead region.

    python -m pytest tests/test_expand.py -q

The 6-account stack fixture (A -> B -> C -> D -> E -> F, one transfer per hop, plus licit noise)
is shared with the 6.4 policy test: two seeds (B -> C, D -> E) must reach the four quiet hops
through candidates(); the policy test then asserts the greedy expansion recovers them and stops.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ringshield.expand.candidates import COLUMNS, candidates  # noqa: E402
from ringshield.expand.cross_score import fold_assignment  # noqa: E402
from ringshield.expand.dead_region import dead_region_mask, head_constants  # noqa: E402
from ringshield.expand.features import FEATURE_COLUMNS, KEY_COLUMNS, EmbeddingStore, FeatureContext, compute_features  # noqa: E402
from ringshield.expand.index import SplitIndex, index_for  # noqa: E402

H = 3600
A, B, C, D, E, F = 1, 2, 3, 4, 5, 6
STACK_EDGES = [  # edge_id, from, to, ts, amount  -- the ring: 10,000 moves down the stack, 2 h per hop
    (100, A, B, 10 * H, 10000.0), (101, B, C, 12 * H, 9990.0), (102, C, D, 14 * H, 9980.0),
    (103, D, E, 16 * H, 9970.0), (104, E, F, 18 * H, 9960.0),
]
NOISE_EDGES = [  # licit background: near in time at a stack account, or on the stack far in time
    (200, 7, B, 11 * H, 50.0), (201, C, 8, 13 * H, 20.0), (202, 9, 10, 12 * H, 30.0),
    (203, 8, 11, 13 * H + 60, 25.0),          # hop 2 from 201's far endpoint (8)
    (204, A, 12, 200 * H, 40.0),              # on the stack but 8 days later: outside every window
    (205, 13, F, 19 * H, 60.0), (206, 13, 14, 20 * H, 15.0),
]
SEEDS = [101, 103]
QUIET = [100, 102, 104]      # the ring edges no seed covers (plus 101/103 are the seeds themselves)


def stack_frame() -> pd.DataFrame:
    rows = [(e, f, t, 1, 1, ts, amt, amt, 0, 0, 0) for e, f, t, ts, amt in STACK_EDGES + NOISE_EDGES]
    df = pd.DataFrame(rows, columns=["edge_id", "from_id", "to_id", "from_bank", "to_bank", "timestamp",
                                     "amount_sent", "amount_received", "currency_sent", "currency_received", "payment_format"])
    df["score_raw"] = np.where(df["edge_id"].isin(SEEDS), 0.95, np.where(df["edge_id"] < 200, 0.4, 0.05))
    df["score_calibrated"] = df["score_raw"]
    return df.sort_values("edge_id").reset_index(drop=True)


# ------------------------------------------------------------------------- index
def test_index_window_sums_match_brute_force():
    rng = np.random.default_rng(0)
    n = 3000
    df = pd.DataFrame({"edge_id": np.arange(n), "from_id": rng.integers(0, 40, n), "to_id": rng.integers(0, 40, n),
                       "timestamp": rng.integers(0, 10 * H, n), "amount_received": rng.exponential(100, n)})
    idx = SplitIndex.build(df)
    for _ in range(50):
        a, t = int(rng.integers(0, 40)), int(rng.integers(0, 10 * H))
        lo, hi = idx.window(idx.dense([a]), np.array([t - H]), np.array([t]), hi_inclusive=False)
        s = idx.window_sums(lo, hi)
        w = df[(df["timestamp"] >= t - H) & (df["timestamp"] < t)]
        ins, outs = w[w["to_id"] == a], w[w["from_id"] == a]
        assert s["in_cnt"][0] == len(ins) and s["out_cnt"][0] == len(outs)
        assert abs(s["in_amt"][0] - ins["amount_received"].sum()) < 1e-6
        assert abs(s["out_amt"][0] - outs["amount_received"].sum()) < 1e-6
        assert s["in_low"][0] == (ins["amount_received"] < idx.amount_p25).sum()


def test_index_dedup_and_cache():
    df = stack_frame()
    dup = df.iloc[[0]].copy()
    dup["edge_id"] = 999
    df2 = pd.concat([df, dup], ignore_index=True)
    idx = SplitIndex.build(df2)
    assert idx.dup.sum() == 1
    lo, hi = idx.window(idx.dense([B]), np.array([0]), np.array([100 * H]))
    assert idx.window_sums(lo, hi)["in_cnt"][0] == 2       # A->B once (dup weight 0) + noise 7->B
    assert index_for(df) is index_for(df)
    assert index_for(df) is not index_for(df2)


# ------------------------------------------------------------------------- candidates
def test_candidates_stack_hops_and_window():
    df = stack_frame()
    c = candidates(df, SEEDS, delta_t_h=6, max_hops=2)
    assert list(c.columns) == COLUMNS and c["candidate_edge_id"].is_unique
    got = c.set_index("candidate_edge_id")
    assert set(QUIET) <= set(got.index)
    assert all(got.loc[e, "hop"] == 1 for e in QUIET)      # every quiet hop shares an account with a seed
    assert got.loc[102, "n_anchors"] == 2                  # C->D touches both seeds
    assert got.loc[100, "shared_account"] == B and got.loc[104, "shared_account"] == E
    assert got.loc[100, "gap_s"] == -2 * H and got.loc[104, "gap_s"] == 2 * H
    assert 203 in got.index and got.loc[203, "hop"] == 2 and got.loc[203, "via_edge_id"] == 201
    assert 204 not in got.index                            # 8 days later: outside the window
    assert 206 not in got.index                            # only reachable at hop 3
    assert not set(SEEDS) & set(got.index)
    lo, hi = c.attrs["window"]
    assert lo == 12 * H - 6 * H and hi == 16 * H + 6 * H
    assert (df.set_index("edge_id").loc[got.index, "timestamp"].between(lo, hi)).all()
    c1 = candidates(df, SEEDS, delta_t_h=6, max_hops=1)
    assert (c1["hop"] == 1).all() and set(c1["candidate_edge_id"]) == set(got.index[got["hop"] == 1])
    assert candidates(df, [], 6).empty


def test_candidates_dedupe_prefers_closest_anchor():
    df = stack_frame()
    c = candidates(df, [101, 103], delta_t_h=6).set_index("candidate_edge_id")
    assert c.loc[102, "anchor_edge_id"] in (101, 103) and abs(c.loc[102, "gap_s"]) == 2 * H


def test_candidates_hub_truncation_keeps_nearest_in_time():
    df = stack_frame()
    hub = pd.DataFrame({"edge_id": 1000 + np.arange(400), "from_id": 50, "to_id": B, "from_bank": 1, "to_bank": 1,
                        "timestamp": 12 * H + np.arange(-200, 200) * 30, "amount_sent": 1.0, "amount_received": 1.0,
                        "currency_sent": 0, "currency_received": 0, "payment_format": 0, "score_raw": 0.01, "score_calibrated": 0.01})
    df2 = pd.concat([df, hub], ignore_index=True)
    full = candidates(df2, [101], delta_t_h=6, max_hops=1, max_events_per_query=None)
    assert full.attrs["n_truncated"] == 0 and (full["candidate_edge_id"] >= 1000).sum() == 400
    cut = candidates(df2, [101], delta_t_h=6, max_hops=1, max_events_per_query=50)
    assert cut.attrs["n_truncated"] == 1
    kept = cut[cut["candidate_edge_id"] >= 1000]
    assert len(kept) <= 50 and kept["gap_s"].abs().max() <= 25 * 30      # the 50 events nearest 12 h
    assert 100 not in set(cut["candidate_edge_id"])                      # the cost: A->B (2 h away at B) is cut
    assert {102, 201} <= set(cut["candidate_edge_id"])                   # the other endpoint's window untouched


# ------------------------------------------------------------------------- features
def _ctx(df, with_emb=True):
    rng = np.random.default_rng(1)
    emb = EmbeddingStore(df["edge_id"].to_numpy(), rng.normal(size=(len(df), 8)).astype(np.float32)) if with_emb else None
    return FeatureContext.build(df, emb=emb)


def test_features_stack_values_and_causality():
    df = stack_frame()
    c = candidates(df, SEEDS, delta_t_h=6)
    X = compute_features(_ctx(df), c, SEEDS, delta_t_h=6)
    assert list(X.columns) == KEY_COLUMNS + FEATURE_COLUMNS and len(X) == len(c)
    assert not X[FEATURE_COLUMNS].isna().any().any()
    # the causal guarantee, as an assertion on the arrays (not a print)
    assert (X["max_ts_used"] <= X["candidate_ts"]).all()
    assert X["max_included_ts"].eq(16 * H).all()
    x = X.set_index("candidate_edge_id")
    # A->B at B: seed B->C is an outflow of B, the candidate an inflow: closure goes 0 -> ~1
    assert x.loc[100, "cand_is_inflow"] == 1 and x.loc[100, "closure_before"] == 0
    assert x.loc[100, "closure_after"] == pytest.approx(9990 / 10000)
    assert x.loc[100, "hold_time_s"] == 2 * H and x.loc[100, "pair_out_in"] == 1
    # C->D at C (anchor B->C is an inflow at C): in->out, hold time 2 h, closure ~1
    assert x.loc[102, "pair_in_out"] == 1 and x.loc[102, "hold_time_s"] == 2 * H
    assert x.loc[102, "closure_after"] == pytest.approx(9980 / 9990)
    assert x.loc[102, "far_is_member"] == 1                # D is an endpoint of seed D->E
    # reach: from A (far endpoint of A->B) nothing leads back to the ring within the window
    assert x.loc[100, "reach_1hop"] == 0
    # C->D's far endpoint D touches seed account E? no: D->E is the included edge itself (excluded);
    # E->F's far endpoint F has no other contact
    assert x.loc[104, "reach_1hop"] == 0
    assert x.loc[100, "gap_to_nearest_seed_s"] == 2 * H and x.loc[100, "nearest_seed_before"] == 0
    assert x.loc[100, "far_24h_in_cnt"] == 0 and x.loc[101 if 101 in x.index else 100, "n_included"] == 2
    # account state of the shared account B at t = 10 h: nothing before it
    assert x.loc[100, "shared_24h_in_cnt"] == 0
    # for E->F at 18 h: shared E has the inflow D->E (16 h) in the trailing 24 h
    assert x.loc[104, "shared_24h_in_cnt"] == 1 and x.loc[104, "shared_24h_in_sum"] == pytest.approx(9970)
    assert x.loc[104, "shared_24h_uniq_in"] == 1
    assert 0 < x.loc[104, "score_quantile"] < 1 and x.loc[104, "dead_region"] == 0
    assert abs(x.loc[104, "cos_anchor"]) <= 1 and abs(x.loc[104, "cos_mean_included"]) <= 1


def test_features_no_embeddings_gives_nan_cosines_only():
    df = stack_frame()
    c = candidates(df, SEEDS, delta_t_h=6)
    X = compute_features(_ctx(df, with_emb=False), c, SEEDS, delta_t_h=6)
    assert X["cos_anchor"].isna().all() and X["cos_mean_included"].isna().all()
    assert not X[[f for f in FEATURE_COLUMNS if not f.startswith("cos_")]].isna().any().any()


def test_features_never_read_after_candidate_timestamp_on_real_data():
    """Every feature row's max_ts_used <= its candidate's timestamp on real val rings (skips
    without the data on disk)."""
    se_path = REPO_ROOT / "contract" / "out" / "scored_edges_gine_causal_1_val.parquet"
    val_path = REPO_ROOT / "data" / "processed" / "amlworld_val.parquet"
    if not (se_path.exists() and val_path.exists()):
        pytest.skip("val contract file / split not on disk")
    se = pd.read_parquet(se_path)
    val = pd.read_parquet(val_path, columns=["EdgeID", "ring_id"])
    ctx = FeatureContext.build(se)
    seeds = set(se.loc[se["is_seed"], "edge_id"])
    rings = val[val["ring_id"] > 0].groupby("ring_id")["EdgeID"].apply(list)
    checked = 0
    for rid, edges in rings.items():
        s = [e for e in edges if e in seeds]
        if not s:
            continue
        c = candidates(se, s, 72, 2)
        X = compute_features(ctx, c.head(3000), s, 72)      # head: keep the test short
        assert (X["max_ts_used"] <= X["candidate_ts"]).all(), rid
        checked += 1
        if checked >= 5:
            break
    assert checked


# ------------------------------------------------------------------------- folds, dead region
def test_fold_assignment_is_contiguous_and_balanced():
    counts = {0: 1114921, 1: 754449, 2: 207382, 3: 207430, 4: 482650, 5: 482089}
    folds = fold_assignment(counts, 5)
    assert folds == [[0], [1], [2, 3], [4], [5]]
    assert [d for f in folds for d in f] == sorted(counts)


def test_dead_region_constants_and_mask():
    import torch
    torch.manual_seed(0)
    sd = {"mlp.0.node__to__node.weight": torch.randn(50, 198), "mlp.0.node__to__node.bias": torch.randn(50),
          "mlp.3.node__to__node.weight": torch.randn(25, 50), "mlp.3.node__to__node.bias": torch.randn(25),
          "mlp.6.node__to__node.weight": torch.randn(2, 25), "mlp.6.node__to__node.bias": torch.randn(2)}
    c1, c2 = head_constants(sd)
    b2, W3, b3 = sd["mlp.3.node__to__node.bias"], sd["mlp.6.node__to__node.weight"], sd["mlp.6.node__to__node.bias"]
    assert c1 == pytest.approx(torch.softmax(W3 @ torch.relu(b2) + b3, 0)[1].item())
    assert c2 == pytest.approx(torch.softmax(b3, 0)[1].item())
    s = np.array([c1, c2, c1 * (1 + 1e-7), 0.5, 0.0])
    assert dead_region_mask(s, [c1, c2]).tolist() == [True, True, True, False, False]


def test_r1_dead_region_matches_the_score_plateaus():
    ckpt = REPO_ROOT / "experiments" / "R1_gine_causal" / "model_best_seed1.pt"
    sc = REPO_ROOT / "experiments" / "R1_gine_causal" / "scores_val_seed1.parquet"
    if not (ckpt.exists() and sc.exists()):
        pytest.skip("R1 seed 1 not on disk")
    import torch
    consts = head_constants(torch.load(ckpt, map_location="cpu", weights_only=True))
    s = pd.read_parquet(sc)["score_raw"].to_numpy()
    m = dead_region_mask(s, consts)
    assert m.sum() > 0.05 * len(s)                          # a real plateau, not a rounding accident
    top = pd.Series(s).value_counts().index[0]
    assert dead_region_mask(np.array([top]), consts)[0]     # the most common score IS a head constant


def test_training_set_has_no_val_or_test_timestamps():
    """Every training row's candidate and every included edge lie inside the train split."""
    ts_path = REPO_ROOT / "experiments" / "R3_expansion" / "training_set.parquet"
    if not ts_path.exists():
        ts_path = REPO_ROOT / "experiments" / "R3_expansion_dryrun" / "training_set_dryrun.parquet"
    if not ts_path.exists():
        pytest.skip("training set not built yet (ringshield/expand/make_training_set.py)")
    tr = pd.read_parquet(REPO_ROOT / "data" / "processed" / "amlworld_train.parquet", columns=["Timestamp"])
    lo, hi = int(tr["Timestamp"].min()), int(tr["Timestamp"].max())
    X = pd.read_parquet(ts_path, columns=["candidate_ts", "max_ts_used", "max_included_ts", "day"])
    assert X["candidate_ts"].between(lo, hi).all() and X["max_included_ts"].between(lo, hi).all()
    assert (X["max_ts_used"] <= X["candidate_ts"]).all()
    assert (X["day"] >= 1).all()                             # day-0 rows dropped (amendment b)


# ------------------------------------------------------------------------- 6.4 policy / expansion
from ringshield.aggregators.expand import aggregate_expand, expand_component, seed_components, truncate  # noqa: E402
from ringshield.expand.policy import Policy, feature_columns  # noqa: E402

G = 7
STACK7 = [  # A -> B -> C -> D -> E -> F -> G, 2 h per hop, 10,000 draining by 10 per hop
    (300, A, B, 10 * H, 10000.0), (301, B, C, 12 * H, 9990.0), (302, C, D, 14 * H, 9980.0),
    (303, D, E, 16 * H, 9970.0), (304, E, F, 18 * H, 9960.0), (305, F, G, 20 * H, 9950.0),
]
SEEDS7 = [301, 304]
QUIET7 = [300, 302, 303, 305]
NOISE7 = [(400, 7, B, 11 * H, 50.0), (401, C, 8, 13 * H, 20.0), (402, 9, D, 15 * H, 30.0), (403, 8, 11, 13 * H + 60, 25.0),
          (404, A, 12, 200 * H, 40.0), (405, 13, F, 19 * H, 60.0), (406, G, 14, 25 * H, 9950.0),   # 406: balances G but after the seed window
          (407, 15, 16, 12 * H, 10.0)]


def stack7_frame() -> pd.DataFrame:
    rows = [(e, f, t, 1, 1, ts, amt, amt, 0, 0, 0) for e, f, t, ts, amt in STACK7 + NOISE7]
    df = pd.DataFrame(rows, columns=["edge_id", "from_id", "to_id", "from_bank", "to_bank", "timestamp",
                                     "amount_sent", "amount_received", "currency_sent", "currency_received", "payment_format"])
    df["score_raw"] = np.where(df["edge_id"].isin(SEEDS7), 0.95, np.where(df["edge_id"] < 400, 0.4, 0.05))
    df["score_calibrated"] = df["score_raw"]
    return df.sort_values("edge_id").reset_index(drop=True)


class ConservationPolicy(Policy):
    """Stub for the fixture: a hop-1 candidate is a member iff it improves the shared account's balance
    to (nearly) closed."""

    def __init__(self):
        super().__init__("model", feature_columns())

    def predict(self, X):
        return np.where((X["hop"] == 1) & (X["closure_after"] >= 0.9) & (X["closure_before"] < 0.9), 1.0, 0.0)


def test_fixture_stack_two_seeds_recover_four_quiet_hops_and_stop():
    df = stack7_frame()
    ctx = _ctx(df, with_emb=False)
    tr = expand_component(df, SEEDS7, ConservationPolicy(), ctx, delta_t_h=6, p_floor=0.5)
    added = [a[0] for a in tr["adds"]]
    assert sorted(added) == QUIET7                      # the four quiet hops, nothing else
    assert tr["stop"] == "closure"                      # every included account with both flows closes >= 0.98
    assert tr["n_iter"] == 4 and all(a[1] == 1.0 for a in tr["adds"])
    assert tr["window"] == (12 * H - 6 * H, 18 * H + 6 * H)
    # prefix truncation: a higher p_min is a prefix of the same trajectory
    assert truncate(tr, 0.7) == added and truncate(tr, 1.5) == []


def test_expansion_never_leaves_the_seed_window():
    """406 (G -> 14 at 25 h) balances G once F -> G (20 h) is included and lies within delta_t = 6 h of
    it, so the growing included set would reach it -- but it is outside the SEED window
    [12 h - 6 h, 18 h + 6 h] and must never be added."""
    df = stack7_frame()
    ctx = _ctx(df, with_emb=False)
    tr = expand_component(df, SEEDS7, ConservationPolicy(), ctx, delta_t_h=6, p_floor=0.5)
    added = [a[0] for a in tr["adds"]]
    assert 305 in added and 406 not in added
    lo, hi = tr["window"]
    assert (lo, hi) == (6 * H, 24 * H)
    ts = df.set_index("edge_id")["timestamp"]
    assert all(lo <= ts.loc[e] <= hi for e in added)
    from ringshield.expand.candidates import candidates
    assert 406 in set(candidates(df, SEEDS7 + [305], delta_t_h=6)["candidate_edge_id"])          # reachable from the included set
    assert 406 not in set(candidates(df, SEEDS7 + [305], delta_t_h=6, time_bounds=(lo, hi))["candidate_edge_id"])  # not inside the seed window
    # the in-code assertion, exercised directly: a candidate generator that ignores the window plus a
    # policy that takes every hop-1 candidate must trip it
    from ringshield.aggregators import expand as E

    class TakeAll(Policy):
        def __init__(self):
            super().__init__("model", feature_columns())

        def predict(self, X):
            return np.where(X["hop"] == 1, 1.0, 0.0)

    E.candidates = lambda se, inc, dt, hops, **k: candidates(se, inc, dt, hops, index=k.get("index"))
    try:
        with pytest.raises(AssertionError, match="outside the seed window"):
            expand_component(df, SEEDS7, TakeAll(), ctx, delta_t_h=6, p_floor=0.5)
    finally:
        E.candidates = candidates


def test_aggregate_expand_builds_rings_with_expanded_edges():
    df = stack7_frame()
    ctx = _ctx(df, with_emb=False)
    rep = {}
    rings = aggregate_expand(df, seed_frac_pct=15.0, min_size=3, policy=ConservationPolicy(), ctx=ctx, p_min=0.5,
                             delta_t_h=6, report=rep)
    assert len(rings) == 1
    r = rings[0]
    assert r.aggregator_id == "expand" and sorted(r.seed_edges) == SEEDS7 and sorted(r.expanded_edges) == QUIET7
    assert r.members == [A, B, C, D, E, F, G] and set(r.seed_edges + r.expanded_edges) <= set(r.member_edges)
    assert r.conservation_closure == pytest.approx(np.mean([9990 / 10000, 9980 / 9990, 9970 / 9980, 9960 / 9970, 9950 / 9960]))
    assert rep["n_expanded_edges"] == 4 and rep["n_rings_with_expansion"] == 1
    # the rule baselines: B1 takes every hop-1 candidate in one pass, B1b only those above the quantile
    b1 = aggregate_expand(df, seed_frac_pct=15.0, min_size=3, policy=Policy.rule("rule"), ctx=ctx, p_min=1.0, delta_t_h=6)
    assert set(b1[0].expanded_edges) > set(QUIET7)      # noise at B / C / D / F comes along
    rule_q = Policy("rule_q", ["hop", "score_quantile"], hop1_only=True, q_min=0.6)   # 14 edges: 0.99 would select nothing
    b1b = aggregate_expand(df, seed_frac_pct=15.0, min_size=3, policy=rule_q, ctx=ctx, p_min=1.0, delta_t_h=6)
    assert set(b1b[0].expanded_edges) == set(QUIET7)     # the ring edges score 0.4 > every noise edge -> top quantiles
    comps = seed_components(df, df["edge_id"].isin(SEEDS7).to_numpy())
    assert comps == [[301], [304]]


def test_policy_train_and_load_roundtrip(tmp_path):
    """A tiny LightGBM policy trains, saves and reloads; drop-group and hop1_only are honoured."""
    from ringshield.expand.policy import train_policy
    rng = np.random.default_rng(0)
    n = 600
    X = pd.DataFrame(rng.normal(size=(n, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    X["hop"] = rng.integers(1, 3, n)
    X["ring_id"] = rng.integers(0, 30, n)
    X["label"] = ((X["closure_after"] > 0.8) & (X["hop"] == 1)).astype(int)
    if X["label"].sum() < 10:
        X.loc[:20, "label"] = 1
    pol = train_policy(X, drop_groups=("embedding",), verbose=False)
    assert "cos_anchor" not in pol.features and pol.meta["cv"]["cv_auc_pr_mean"] is not None
    pol.save(tmp_path / "pol")
    back = Policy.load(tmp_path / "pol")
    assert back.features == pol.features and back.drop_groups == ("embedding",)
    p = back.predict(X.head(50))
    assert p.shape == (50,) and np.allclose(p, pol.predict(X.head(50)))
    h1 = train_policy(X, hop1_only=True, verbose=False)
    assert (h1.predict(X[X["hop"] == 2].head(5)) == 0).all()


def test_cli_export_and_run_expand(tmp_path):
    """export-model from a run_expand output, then `python -m ringshield run --aggregator expand` on a 1 %
    sample of the contract file with --gfp / --embeddings (skips without the R3 run on disk)."""
    import subprocess
    run_dir = REPO_ROOT / "experiments" / "R3_expansion" / "runs" / "proposed" / "seed1"
    scores = REPO_ROOT / "contract" / "out" / "scored_edges_gine_causal_1.parquet"
    emb = REPO_ROOT / "experiments" / "R1_gine_causal" / "embeddings_test_seed1.parquet"
    gfp = REPO_ROOT / "data" / "processed" / "amlworld_gfp_features_test.parquet"
    if not (run_dir / "config.yaml").exists() or not scores.exists() or not emb.exists():
        pytest.skip("R3 proposed run / contract file / embeddings not on disk")
    py = REPO_ROOT / ".venv312" / "Scripts" / "python.exe"
    md = tmp_path / "model_expand"
    r = subprocess.run([str(py), "-m", "ringshield", "export-model", "--run-dir", str(run_dir), "--out-model-dir", str(md)],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    import json
    doc = json.loads((md / "model.json").read_text(encoding="utf-8"))
    assert doc["aggregator"] == "expand" and doc["params"]["policy_kind"] == "model" and (md / "policy" / "policy.txt").exists()
    assert doc["params"]["max_events_per_query"] == 500 and doc["params"]["p_min"] in (0.3, 0.5, 0.7)
    se = pd.read_parquet(scores).sample(frac=0.02, random_state=1).sort_values("edge_id")
    sample = tmp_path / "sample.parquet"
    se.to_parquet(sample, index=False)
    out = tmp_path / "rings.parquet"
    r = subprocess.run([str(py), "-m", "ringshield", "run", "--scores", str(sample), "--model-dir", str(md), "--aggregator", "expand",
                        "--gfp", str(gfp), "--embeddings", str(emb), "--out", str(out)], cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    from ringshield.rings import read_rings_parquet
    rings = read_rings_parquet(out)
    log = json.loads(Path(str(out) + ".log.json").read_text(encoding="utf-8"))
    assert log["aggregator"] == "expand" and log["expansion"] is not None and log["n_expanded_edges"] >= 0
    ids = set(se["edge_id"])
    for ring in rings:
        assert ring.aggregator_id == "expand" and ring.ring_id.startswith("expand-gine_causal-1-")
        assert set(ring.seed_edges) <= ids and set(ring.expanded_edges) <= ids and not set(ring.seed_edges) & set(ring.expanded_edges)
