"""T-P1: evaluation/score_external.py on a hand-built fixture (no AMLworld data needed).

Fixture (window = days 8-9; day_zero 10, 86,400 s/day):
  ring A (STACK)  in-window edges 1-2, 2-3 (piece {1,2,3}) and 4-5, 5-6 (piece {4,5,6});
                  out-of-window edges 3-4 and 6-7 (day 5) -> visible {1..6}, full {1..7}
  ring B (FAN-IN) in-window 10-11; out-of-window 11-12   -> visible {10,11} (2 members)
  ring C (CYCLE)  in-window 20-21, 21-22, 22-23            -> visible {20..23}
Predictions (all edges in window unless said):
  P1 {1,2,3}      P2 {1..6} (spans both pieces of A)      P3 {20,21,22}     P4 {30,31,32} (noise)
  P5 {40,41}      (2 accounts: dropped by min_size 3)
Hand-computed (Jaccard >= 0.5, greedy one-to-one by descending Jaccard):
  test_visible  targets A, B, C.  J(P1,A)=3/6=0.5, J(P2,A)=1.0, J(P3,C)=3/4.
                P2-A (1.0), P3-C (0.75); P1 then finds A used -> matched 2 of 3; precision 2/4.
  full_membership  A = {1..7}: J(P2,A)=6/7, J(P1,A)=3/7 < 0.5; C unchanged -> matched 2 of 3.
  component     targets A#0 {1,2,3}, A#1 {4,5,6}, B#0 {10,11}, C#0 {20..23}.
                P1-A#0 (1.0), P3-C#0 (0.75), P2-A#1 (3/6 = 0.5) -> matched 3 of 4; precision 3/4.
                P2 spans both pieces but is matched to exactly one.
  component_ge3 B's piece (2 accounts) dropped -> 3 targets, matched 3 of 3.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation import score_external as se  # noqa: E402
from evaluation.ring_stats import ring_evidence  # noqa: E402
from ringshield.windows import Window  # noqa: E402

DAY = 86400
Z = 10
W = Window("primary", "test", 8, 9, Z, DAY)


def ts(day, k=0):
    return Z + day * DAY + 100 * (k + 1)


TRUTH_EDGES = [  # ring_id, from, to, day, pattern
    ("A", 1, 2, 8, "STACK"), ("A", 2, 3, 8, "STACK"), ("A", 4, 5, 9, "STACK"), ("A", 5, 6, 9, "STACK"),
    ("A", 3, 4, 5, "STACK"), ("A", 6, 7, 5, "STACK"),
    ("B", 10, 11, 8, "FAN-IN"), ("B", 11, 12, 5, "FAN-IN"),
    ("C", 20, 21, 8, "CYCLE"), ("C", 21, 22, 8, "CYCLE"), ("C", 22, 23, 9, "CYCLE"),
]
NOISE_EDGES = [(30, 31, 8), (31, 32, 8), (40, 41, 8)]


@pytest.fixture()
def world(tmp_path):
    gt = pd.DataFrame([{"ring_id": r, "from_id": f, "to_id": t, "timestamp_int": ts(d, i), "pattern_type": p}
                       for i, (r, f, t, d, p) in enumerate(TRUTH_EDGES)])
    gt_path = tmp_path / "gt.parquet"
    gt.to_parquet(gt_path)
    rows = [(f, t, ts(d, i)) for i, (_, f, t, d, _) in enumerate(TRUTH_EDGES)]
    rows += [(f, t, ts(d, 50 + i)) for i, (f, t, d) in enumerate(NOISE_EDGES)]
    edges = pd.DataFrame(rows, columns=["from_id", "to_id", "timestamp"])
    edges.insert(0, "edge_id", np.arange(len(edges), dtype=np.int64))
    targets, obs = se.build_targets(gt_path, W)
    return SimpleNamespace(gt_path=gt_path, edges=edges, targets=targets, obs=obs, tmp=tmp_path)


def eid(edges, f, t):
    m = edges[(edges.from_id == f) & (edges.to_id == t)]
    assert len(m) == 1
    return int(m.edge_id.iloc[0])


PRED_MEMBERS = {"P1": [1, 2, 3], "P2": [1, 2, 3, 4, 5, 6], "P3": [20, 21, 22], "P4": [30, 31, 32], "P5": [40, 41]}
PRED_EDGES = {"P1": [(1, 2), (2, 3)], "P2": [(1, 2), (2, 3), (4, 5), (5, 6)], "P3": [(20, 21), (21, 22)],
              "P4": [(30, 31), (31, 32)], "P5": [(40, 41)]}


def write_minimal(world, with_edges: bool, suffix=".parquet") -> Path:
    rows = []
    for rid, m in PRED_MEMBERS.items():
        row = {"ring_id": rid, "members": m}
        if with_edges:
            row["member_edges"] = [eid(world.edges, f, t) for f, t in PRED_EDGES[rid]]
        rows.append(row)
    df = pd.DataFrame(rows)
    p = world.tmp / (f"pred_{int(with_edges)}" + suffix)
    if suffix == ".jsonl":
        df.to_json(p, orient="records", lines=True)
    else:
        df.to_parquet(p)
    return p


def write_full(world) -> Path:
    from ringshield.rings import Ring, write_rings_parquet
    rings = []
    for rid, m in PRED_MEMBERS.items():
        me = [eid(world.edges, f, t) for f, t in PRED_EDGES[rid]]
        rings.append(Ring(ring_id=rid, tenant_id=0, aggregator_id="fixture", members=m, n_members=len(m),
                          member_edges=me, seed_edges=me, expanded_edges=[], expanded_edge_probs=[],
                          n_edges=len(me), start_time=0, end_time=0, duration_hours=0.0, confidence=1.0,
                          max_edge_prob=1.0, density=1.0, conservation_closure=float("nan"),
                          topology_type="UNKNOWN", topology_probs=[1.0 / 8] * 8, source_accounts=[],
                          sink_accounts=[], mule_accounts=[]))
    return write_rings_parquet(rings, world.tmp / "pred_full.parquet")


def run_score(world, path, thresholds=(0.5,)):
    rings, info = se.load_predictions(path, world.edges, 3)
    rows, ev = se.score([rings], world.edges, world.targets, W, list(thresholds), 50, 0)
    return {(r["convention"], r["threshold"]): r for r in rows}, ev, info


# --------------------------------------------------------------------------------------------- truth
def test_target_counts_per_convention(world):
    t = world.targets
    assert set(t["test_visible"][0]) == {"A", "B", "C"}
    assert t["test_visible"][0]["A"] == {1, 2, 3, 4, 5, 6}
    assert t["full_membership"][0]["A"] == {1, 2, 3, 4, 5, 6, 7}
    assert t["full_membership"][0]["B"] == {10, 11, 12}
    assert t["component"][0] == {("A", 0): {1, 2, 3}, ("A", 1): {4, 5, 6}, ("B", 0): {10, 11}, ("C", 0): {20, 21, 22, 23}}
    assert set(t["component_ge3"][0]) == {("A", 0), ("A", 1), ("C", 0)}


def test_pieces_partition_visible_members(world):
    tv = world.targets["test_visible"][0]
    comp = world.targets["component"][0]
    for rid, accs in tv.items():
        pieces = [v for k, v in comp.items() if k[0] == rid]
        assert set().union(*pieces) == accs
        assert sum(len(p) for p in pieces) == len(accs)          # disjoint


def test_observability_block(world):
    o = world.obs
    assert o["n_in_scope_rings"] == 3
    assert o["rings_lt3_visible_members"] == 1                     # B
    assert o["rings_no_in_window_piece_ge3"] == 1                  # B
    assert o["rings_split_into_ge2_pieces"] == 1                   # A
    assert o["n_pieces_ge3"] == 3


# --------------------------------------------------------------------------------------------- matching
def test_exact_jaccard_and_one_to_one(world):
    rings, _ = se.load_predictions(write_minimal(world, True), world.edges, 3)
    assert [r.ring_id for r in rings] == ["P1", "P2", "P3", "P4"]                  # P5 dropped by min_size
    tv, pat = world.targets["test_visible"]
    ev = ring_evidence(rings, world.edges, tv, W, method="x", seed=1, patterns=pat, threshold=0.5, causal=True)
    assert ev.matched == {"A": 1, "B": 0, "C": 1}
    assert ev.jaccard["A"] == pytest.approx(1.0)                                   # P2 beats P1 (0.5)
    assert ev.jaccard["C"] == pytest.approx(0.75)
    assert ev.n_predicted == 4


def test_metrics_hand_computed(world):
    res, ev, _ = run_score(world, write_minimal(world, True))
    tv = res[("test_visible", 0.5)]
    assert tv["n_targets"] == 3
    assert tv["ring_recall"] == pytest.approx(2 / 3)
    assert tv["ring_precision"] == pytest.approx(2 / 4)
    assert tv["ring_f1"] == pytest.approx(2 * (0.5 * 2 / 3) / (0.5 + 2 / 3))
    fm = res[("full_membership", 0.5)]
    assert fm["ring_recall"] == pytest.approx(2 / 3)                               # J(P2, A_full) = 6/7
    comp = res[("component", 0.5)]
    assert comp["n_targets"] == 4 and comp["ring_recall"] == pytest.approx(3 / 4)
    assert comp["ring_precision"] == pytest.approx(3 / 4)
    c3 = res[("component_ge3", 0.5)]
    assert c3["n_targets"] == 3 and c3["ring_recall"] == pytest.approx(1.0)


def test_prediction_spanning_two_pieces_matches_only_one(world):
    p = world.tmp / "only_p2.parquet"
    pd.DataFrame([{"ring_id": "P2", "members": PRED_MEMBERS["P2"]}]).to_parquet(p)
    rings, _ = se.load_predictions(p, world.edges, 3)
    comp, pat = world.targets["component"]
    ev = ring_evidence(rings, world.edges, comp, W, method="x", seed=1, patterns=pat, threshold=0.5, causal=True)
    assert sum(ev.matched[k] for k in [("A", 0), ("A", 1)]) == 1


def test_thresholds(world):
    res, _, _ = run_score(world, write_minimal(world, True), thresholds=(0.3, 0.5, 0.7))
    assert res[("test_visible", 0.7)]["ring_recall"] == pytest.approx(2 / 3)       # 1.0 and 0.75 both >= 0.7
    assert res[("component", 0.7)]["ring_recall"] == pytest.approx(2 / 4)          # P2-A#1 (0.5) drops out
    assert res[("full_membership", 0.3)]["ring_recall"] == pytest.approx(2 / 3)


# --------------------------------------------------------------------------------------------- schemas
def test_minimal_and_full_schema_identical(world):
    full, _, info_f = run_score(world, write_full(world))
    with_e, _, info_e = run_score(world, write_minimal(world, True))
    induced, _, info_i = run_score(world, write_minimal(world, False))
    jsonl, _, _ = run_score(world, write_minimal(world, False, ".jsonl"))
    assert info_f["schema"] == "full" and info_e["schema"] == "minimal" and "induced" in info_i["schema"]
    keys = ("ring_precision", "ring_recall", "ring_f1", "ring_f1_lo", "ring_f1_hi", "member_coverage")
    for k in full:
        for m in keys:
            assert full[k][m] == pytest.approx(with_e[k][m]) == pytest.approx(induced[k][m]) == pytest.approx(jsonl[k][m]), (k, m)


def test_induced_edges_drop_out_of_window_link(world):
    # P2's induced edges include the day-5 edge 3-4; the window restriction removes it, so the
    # restricted member set is still {1..6} and nothing outside the window leaks in.
    ie = se.induced_edges([set(PRED_MEMBERS["P2"])], world.edges)[0]
    assert eid(world.edges, 3, 4) in ie


# --------------------------------------------------------------------------------------------- compare / CLI
def test_compare_identical_runs_gives_zero(world):
    p = write_minimal(world, True)
    _, ev, _ = run_score(world, p)
    for d in ("a", "b"):
        (world.tmp / d).mkdir()
        (world.tmp / d / "evidence.json").write_text(json.dumps(ev))
    rows = se.compare(world.tmp / "a", world.tmp / "b", n_boot=200, seed=20261114)
    f1 = [r for r in rows if r["metric"] == "ring_f1"]
    assert f1 and all(r["delta"] == 0 and r["ci_lo"] == 0 and r["ci_hi"] == 0 for r in f1)


def test_evidence_stat_matches_point_metrics(world):
    _, ev, _ = run_score(world, write_minimal(world, True))
    stat, n = se.evidence_stat(ev["test_visible@0.5"])
    out = stat(np.ones((1, n)))
    assert out["ring_f1"][0] == pytest.approx(2 * (0.5 * 2 / 3) / (0.5 + 2 / 3))


def test_cli_help():
    with pytest.raises(SystemExit) as e:
        se.main(["--help"])
    assert e.value.code == 0
