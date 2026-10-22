"""Step 8 -- account roles, rerun_ring, the rule scorer and the typing head.

    python -m pytest tests/test_roles_typing.py -q

Fixtures: one hand-built ring per role and one per topology type, all tiny and explicit, so a
change in `configs/roles.yaml` or in `ringshield/typing/rules.py` shows up here first.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.schema import RINGS_ORDER, TOPOLOGY_TYPES  # noqa: E402
from ringshield.rings import Ring  # noqa: E402
from ringshield.roles import (RingRerunner, account_roles, conservation_closure, dedup_edges, flows_of,  # noqa: E402
                              load_roles_config, rerun_ring, ring_confidence, role_arrays, role_of)
from ringshield.typing.features import RING_FEATURES, ring_features  # noqa: E402
from ringshield.typing.rules import rule_probs, rule_type  # noqa: E402

H = 3600
DAY = 24 * H


def frame(rows) -> pd.DataFrame:
    """rows: (edge_id, from, to, ts, amount)"""
    df = pd.DataFrame(rows, columns=["edge_id", "from_id", "to_id", "timestamp", "amount_received"])
    df["amount_sent"] = df["amount_received"]
    df["from_bank"] = df["to_bank"] = 1
    for c in ("currency_sent", "currency_received", "payment_format"):
        df[c] = 0
    df["score_raw"] = 0.9
    df["score_calibrated"] = 0.8
    df["is_seed"] = True
    return df.sort_values("edge_id").reset_index(drop=True)


def ring_of(df: pd.DataFrame, seed_edges=None, expanded=()) -> Ring:
    members = sorted(set(df["from_id"]) | set(df["to_id"]))
    seed_edges = sorted(df["edge_id"]) if seed_edges is None else sorted(seed_edges)
    r = Ring.baseline(ring_id="t-0", tenant_id=1, aggregator_id="full", members=members,
                      member_edges=sorted(df["edge_id"]), seed_edges=seed_edges, n_edges=len(df),
                      start_time=int(df["timestamp"].min()), end_time=int(df["timestamp"].max()),
                      confidence=0.0, max_edge_prob=0.9, density=0.0)
    r.expanded_edges = sorted(expanded)
    r.expanded_edge_probs = [0.8] * len(r.expanded_edges)
    return r


# ------------------------------------------------------------------------ roles
def test_one_fixture_per_role():
    #   1 -> 2 -> 3 : 2 is a mule (passes 1000 on in 2 h); 1 is a source; 3 is a sink
    #   4 -> 5      : 5 holds the money (no outflow at all -> sink), 4 source
    #   6 -> 7 -> 8 : 7 receives 1000 and sends it on five days later -> holder
    #   9 <-> 10    : 9 sends 1000 and receives 100 back -> unbalanced both ways -> peripheral
    df = frame([(1, 1, 2, 10 * H, 1000.0), (2, 2, 3, 12 * H, 1000.0),
                (3, 4, 5, 10 * H, 500.0),
                (4, 6, 7, 10 * H, 1000.0), (5, 7, 8, 10 * H + 5 * DAY, 1000.0),
                (6, 9, 10, 10 * H, 1000.0), (7, 10, 9, 11 * H, 400.0)])
    roles = account_roles(ring_of(df), df)
    got = {a: d["role"] for a, d in roles.items()}
    assert got[1] == "source" and got[3] == "sink"
    assert got[2] == "mule" and roles[2]["hold_time_s"] == 2 * H and roles[2]["closure"] == 1.0
    assert got[4] == "source" and got[5] == "sink"
    assert got[7] == "holder" and roles[7]["hold_time_s"] == 5 * DAY
    assert got[9] == "peripheral" and got[10] == "peripheral"
    arrays = role_arrays(roles)
    assert arrays["source_accounts"] == [1, 4, 6] and arrays["sink_accounts"] == [3, 5, 8]
    assert arrays["mule_accounts"] == [2, 7]                      # mule + holder, per configs/roles.yaml


def test_role_thresholds_and_dedup():
    cfg = load_roles_config()
    assert role_of(0.0, 100.0, 0.0, math.nan, cfg) == "source"
    assert role_of(100.0, 0.0, 0.0, math.nan, cfg) == "sink"
    assert role_of(10.0, 100.0, 0.1, math.nan, cfg) == "source"    # inflow/outflow 0.1 < tau
    assert role_of(100.0, 10.0, 0.1, math.nan, cfg) == "sink"
    assert role_of(100.0, 80.0, 0.8, 3600, cfg) == "mule"
    assert role_of(100.0, 80.0, 0.8, 10 * DAY, cfg) == "holder"
    assert role_of(100.0, 50.0, 0.5, 3600, cfg) == "peripheral"
    df = frame([(1, 1, 2, 10 * H, 1000.0), (2, 1, 2, 10 * H, 1000.0)])   # exact duplicate
    assert len(dedup_edges(df)) == 1
    f = flows_of(df).set_index("account")
    assert f.loc[1, "outflow"] == 1000.0 and f.loc[2, "inflow"] == 1000.0


def test_conservation_closure_and_confidence():
    df = frame([(1, 1, 2, 10 * H, 1000.0), (2, 2, 3, 12 * H, 1000.0)])
    roles = account_roles(ring_of(df), df)
    assert conservation_closure(roles) == pytest.approx(1.0)       # 1000 out of the source, 1000 into the sink
    df2 = frame([(1, 1, 2, 10 * H, 1000.0), (2, 2, 3, 12 * H, 600.0)])
    roles2 = account_roles(ring_of(df2), df2)
    assert conservation_closure(roles2) == pytest.approx(0.6)      # |600 - 1000| / 1000
    df3 = frame([(1, 1, 2, 10 * H, 1000.0), (2, 2, 1, 11 * H, 1000.0)])   # a closed loop: no source, no sink
    assert math.isnan(conservation_closure(account_roles(ring_of(df3), df3)))
    assert ring_confidence(0.8, 0.5) == pytest.approx(0.4)
    assert ring_confidence(0.8, float("nan")) == pytest.approx(0.8)        # closure factor dropped, counted in the log


# ------------------------------------------------------------------------ rule scorer
def _rule(df, expanded=()):
    r = ring_of(df, expanded=expanded)
    return rule_type(ring_features(df, account_roles(r, df)))


def test_rule_scorer_on_one_ring_per_type():
    # FAN-IN: three sources into one sink
    assert _rule(frame([(1, 1, 9, 10 * H, 100.0), (2, 2, 9, 11 * H, 100.0), (3, 3, 9, 12 * H, 100.0)])) == "FAN-IN"
    # FAN-OUT: one source to three sinks
    assert _rule(frame([(1, 9, 1, 10 * H, 100.0), (2, 9, 2, 11 * H, 100.0), (3, 9, 3, 12 * H, 100.0)])) == "FAN-OUT"
    # GATHER-SCATTER: 9 gathers from two and scatters to two
    assert _rule(frame([(1, 1, 9, 10 * H, 100.0), (2, 2, 9, 11 * H, 100.0),
                        (3, 9, 3, 12 * H, 100.0), (4, 9, 4, 13 * H, 100.0)])) == "GATHER-SCATTER"
    # SCATTER-GATHER: one source -> two mules -> one sink (two hubs, pass-throughs between them)
    assert _rule(frame([(1, 1, 2, 10 * H, 100.0), (2, 1, 3, 10 * H, 100.0),
                        (3, 2, 4, 12 * H, 100.0), (4, 3, 4, 12 * H, 100.0)])) == "SCATTER-GATHER"
    # CYCLE: 1 -> 2 -> 3 -> 1
    assert _rule(frame([(1, 1, 2, 10 * H, 100.0), (2, 2, 3, 11 * H, 100.0), (3, 3, 1, 12 * H, 100.0)])) == "CYCLE"
    # BIPARTITE: three disjoint pairs (the fragment a split shows)
    assert _rule(frame([(1, 1, 2, 10 * H, 100.0), (2, 3, 4, 11 * H, 100.0), (3, 5, 6, 12 * H, 100.0)])) == "BIPARTITE"
    # STACK: a single chain of four hops
    assert _rule(frame([(1, 1, 2, 10 * H, 100.0), (2, 2, 3, 11 * H, 100.0), (3, 3, 4, 12 * H, 100.0),
                        (4, 4, 5, 13 * H, 100.0)])) == "STACK"
    # RANDOM: a two-hop chain matches nothing above
    assert _rule(frame([(1, 1, 2, 10 * H, 100.0), (2, 2, 3, 11 * H, 100.0)])) == "RANDOM"


def test_rule_probs_agree_with_rule_type_and_sum_to_one():
    df = frame([(1, 1, 9, 10 * H, 100.0), (2, 2, 9, 11 * H, 100.0), (3, 3, 9, 12 * H, 100.0)])
    f = ring_features(df, account_roles(ring_of(df), df))
    p = rule_probs(f)
    assert len(p) == len(TOPOLOGY_TYPES) and p.sum() == pytest.approx(1.0)
    assert TOPOLOGY_TYPES[int(np.argmax(p))] == rule_type(f)
    assert set(RING_FEATURES) == set(f) and not any(isinstance(v, float) and math.isnan(v) for v in f.values())


def test_rule_accuracy_on_true_train_rings_is_the_sanity_bound():
    """Check 1: the rule scorer reproduces the true type on >= 60 % of true train rings."""
    from ringshield.typing.truth_rings import truth_ring_rows
    if not (REPO_ROOT / "data" / "processed" / "amlworld_train.parquet").exists():
        pytest.skip("train split not on disk")
    d = truth_ring_rows("train", min_members=3)
    acc = float(np.mean([rule_type(r) == r["pattern_type"] for r in d.to_dict("records")]))
    assert acc >= 0.60, f"rule accuracy {acc:.3f} on {len(d)} true train rings"


# ------------------------------------------------------------------------ rerun_ring
def _chain_frame(n_edges: int) -> pd.DataFrame:
    rows = [(100 + k, k + 1, k + 2, 10 * H + k * H, 1000.0 - k) for k in range(n_edges)]
    return frame(rows)


def test_rerun_ring_cc_is_deterministic_and_reports_the_largest_group():
    df = _chain_frame(6)
    a = rerun_ring(df, "cc")
    b = rerun_ring(df, "cc")
    assert a == b and a["features_degraded"] is False
    assert a["n_rings"] == 1 and len(a["largest_ring_edges"]) == 6
    # confidence = mean score_calibrated (0.8) x closure; the chain loses 1 unit per hop, so the
    # sink receives 995 of the source's 1000 -> closure 0.995
    assert a["confidence"] == pytest.approx(0.8 * 0.995)
    # drop the middle edge: two groups, the larger one has three edges
    out = rerun_ring(df[df["edge_id"] != 103], "cc")
    assert out["n_rings"] == 2 and len(out["largest_ring_edges"]) == 3


def _affinity():
    aff_dir = REPO_ROOT / "experiments" / "R4_partition" / "affinity"
    if not (aff_dir / "affinity.txt").exists():
        pytest.skip("trained affinity not on disk")
    from ringshield.partition.affinity import Affinity
    return Affinity.load(aff_dir)


def test_rerun_ring_full_is_deterministic_and_within_the_xai_budget():
    """p95 (not the mean) must stay under 50 ms: the XAI layer's budget is per call, and a mean
    hides the occasional GC spike."""
    aff = _affinity()
    df = _chain_frame(30)
    first = rerun_ring(df, "full", affinity=aff, cut=0.5, min_size=3)
    again = rerun_ring(df, "full", affinity=aff, cut=0.5, min_size=3)
    assert first == again                                       # deterministic
    assert first["n_rings"] >= 1 and first["largest_ring_edges"]
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        rerun_ring(df, "full", affinity=aff, cut=0.5, min_size=3)
        times.append((time.perf_counter() - t0) * 1000)
    p95 = sorted(times)[int(0.95 * len(times)) - 1]
    assert p95 < 50, f"rerun_ring p95 {p95:.1f} ms for a 30-edge ring (budget 50 ms); mean {sum(times)/len(times):.1f} ms"


def test_ring_rerunner_caches_the_index_and_matches_the_one_shot_call():
    aff = _affinity()
    df = _chain_frame(30)
    rr = RingRerunner(df, "full", affinity=aff, cut=0.5, min_size=3)
    assert rr.run() == rerun_ring(df, "full", affinity=aff, cut=0.5, min_size=3)
    ids = df["edge_id"].tolist()
    assert rr.without(ids[3]) == rr.without(ids[3])             # deterministic across calls
    rr.without(ids[0])
    times = []
    for e in ids:
        t0 = time.perf_counter()
        out = rr.without(e)
        times.append((time.perf_counter() - t0) * 1000)
        assert e not in out["largest_ring_edges"]
    p95 = sorted(times)[int(0.95 * len(times)) - 1]
    assert p95 < 50, f"leave-one-out p95 {p95:.1f} ms"
    assert sum(times) < 2000, f"a 30-edge ring's leave-one-out took {sum(times)/1000:.2f} s (XAI budget 2 s)"


def test_rerun_ring_flags_a_degraded_feature_set():
    """Without the GFP table / embeddings the `full` grouping runs on cos_gfp = 0 and cos_emb = NaN,
    which is not the feature set the shipped rings were built with -- the result says so."""
    aff = _affinity()
    df = _chain_frame(12)
    assert rerun_ring(df, "full", affinity=aff)["features_degraded"] is True
    gfp = pd.DataFrame({"EdgeID": df["edge_id"], **{c: 1.0 for c in
                        ["fan_out", "fan_in", "deg_out_src", "deg_in_src", "deg_out_dst", "deg_in_dst",
                         "scatter_gather", "gather_scatter", "temporal_cycle", "cycle_length"]}})
    from ringshield.expand.features import EmbeddingStore
    emb = EmbeddingStore(df["edge_id"].to_numpy(), np.ones((len(df), 8), dtype=np.float32))
    assert rerun_ring(df, "full", affinity=aff, gfp=gfp, emb=emb)["features_degraded"] is False
    assert rerun_ring(df, "cc")["features_degraded"] is False   # cc uses no such features


# ------------------------------------------------------------------------ contract v1
def test_ring_contract_has_expanded_edge_probs():
    assert RINGS_ORDER.index("expanded_edge_probs") == RINGS_ORDER.index("expanded_edges") + 1
    df = frame([(1, 1, 2, 10 * H, 100.0), (2, 2, 3, 11 * H, 100.0)])
    r = ring_of(df, seed_edges=[1], expanded=[2])
    assert len(r.expanded_edge_probs) == len(r.expanded_edges)
    assert list(r.to_dict()) == RINGS_ORDER
