"""Step 4.1: ringshield package -- Ring contract, aggregate_cc reproduces the legacy aggregator,
member/seed edge semantics, CLI wrapper unchanged.

    python -m pytest tests/test_ringshield_cc.py -q
"""
from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.schema import E7_RING_CSV_COLUMNS, RINGS_ORDER, TOPOLOGY_TYPES  # noqa: E402
from ringshield.aggregators.cc import aggregate_cc, threshold_for_pct  # noqa: E402
from ringshield.rings import RINGS_PA_SCHEMA, Ring, read_rings_parquet, rings_to_dataframe, write_rings_parquet  # noqa: E402
from ringshield.truth import load_ground_truth, split_window  # noqa: E402

SCORED = REPO_ROOT / "contract" / "out" / "scored_edges_gine_1.parquet"
LEGACY_CSV = REPO_ROOT / "experiments" / "legacy_E7_test_tuned" / "rings_gine.csv"
LEGACY_PREDS = REPO_ROOT / "experiments" / "E6_tgn" / "predictions_with_ids.csv"
GT = REPO_ROOT / "data" / "processed" / "amlworld_ring_ground_truth.parquet"
TEST_PQ = REPO_ROOT / "data" / "processed" / "amlworld_test.parquet"
STUB = REPO_ROOT / "contract" / "out" / "rings_stub_cc.parquet"
OFFSET = 10  # configs/paths.yaml legacy_csv_time_offset_s
PY = REPO_ROOT / ".venv312" / "Scripts" / "python.exe"


def _toy_scored_edges() -> pd.DataFrame:
    """Two triangles (A: 1-2-3, B: 4-5-6) joined by nothing, plus a low-score edge and a 2-node pair."""
    rows = [
        # edge_id, from, to, from_bank, to_bank, ts, score
        (0, 1, 2, 10, 10, 100, 0.9), (1, 2, 3, 10, 11, 200, 0.8), (2, 3, 1, 11, 10, 300, 0.7),
        (3, 1, 2, 10, 10, 250, 0.95),          # parallel edge inside A (same pair, within window)
        (4, 2, 1, 10, 10, 5000, 0.1),          # low score, member edge of A? no: outside the window
        (5, 4, 5, 20, 20, 400, 0.85), (6, 5, 6, 20, 20, 500, 0.6), (7, 6, 4, 20, 20, 600, 0.65),
        (8, 7, 8, 30, 30, 700, 0.99),          # 2-node component: dropped by min_size 3
        (9, 3, 2, 11, 10, 220, np.nan),        # unscored, inside A's window -> member edge, not seed
        (10, 9, 9, 40, 40, 800, 0.05),         # licit noise
    ]
    return pd.DataFrame(rows, columns=["edge_id", "from_id", "to_id", "from_bank", "to_bank", "timestamp", "score_raw"])


def test_ring_matches_contract():
    assert [f.name for f in dataclasses.fields(Ring)] == RINGS_ORDER
    r = Ring.baseline(ring_id="cc-0", tenant_id=1, aggregator_id="cc", members=[3, 1, 2], member_edges=[5, 6],
                      seed_edges=[5], n_edges=2, start_time=100, end_time=7300, confidence=0.5, max_edge_prob=0.9,
                      density=1 / 3)
    assert r.members == [1, 2, 3] and r.n_members == 3 and r.duration_hours == 2.0
    assert r.expanded_edges == [] and r.topology_type == "UNKNOWN" and len(r.topology_probs) == len(TOPOLOGY_TYPES)
    assert abs(sum(r.topology_probs) - 1) < 1e-12 and r.source_accounts == r.sink_accounts == r.mule_accounts == []
    assert np.isnan(r.conservation_closure)
    assert list(r.to_dict()) == RINGS_ORDER


def test_toy_aggregation_semantics():
    se = _toy_scored_edges()
    rings = aggregate_cc(se, seed_frac_pct=100.0, min_size=3, threshold=0.5)
    assert [r.members for r in rings] == [[1, 2, 3], [4, 5, 6]]      # sorted by confidence desc
    a, b = rings
    assert a.n_edges == 3 and a.density == pytest.approx(3 / 6)      # parallel edge counted once
    assert a.confidence == pytest.approx(np.mean([0.9, 0.8, 0.7, 0.95])) and a.max_edge_prob == 0.95
    assert (a.start_time, a.end_time) == (100, 300)
    assert sorted(a.seed_edges) == [0, 1, 2, 3]                       # the thresholded edges
    assert sorted(a.member_edges) == [0, 1, 2, 3, 9]                  # + the unscored edge inside the window
    assert a.tenant_id == 10                                          # banks 10, 10, 11 -> 10
    assert b.seed_edges == b.member_edges and sorted(b.seed_edges) == [5, 6, 7] and b.tenant_id == 20
    assert a.ring_id == "cc-0" and b.ring_id == "cc-1" and a.aggregator_id == "cc"
    # percentile cut: top 60% of the 10 scored edges keeps 6 (0.7 .. 0.99) -> triangle A complete,
    # B has only its 0.85 edge and the 2-node pair its 0.99 edge -> only A survives min_size 3
    thr = threshold_for_pct(se["score_raw"].to_numpy(), 60.0)
    assert (se["score_raw"] >= thr).sum() == 6
    assert [r.members for r in aggregate_cc(se, seed_frac_pct=60.0, min_size=3)] == [[1, 2, 3]]


def test_parquet_roundtrip(tmp_path):
    rings = aggregate_cc(_toy_scored_edges(), 100.0, 3, threshold=0.5)
    p = write_rings_parquet(rings, tmp_path / "rings.parquet")
    assert pq.read_schema(p).equals(RINGS_PA_SCHEMA)
    back = read_rings_parquet(p)
    assert [r.to_dict() for r in back] == [r.to_dict() for r in rings] or all(
        (x.to_dict() | {"conservation_closure": 0}) == (y.to_dict() | {"conservation_closure": 0})
        for x, y in zip(back, rings))
    df = rings_to_dataframe(rings)
    assert list(df.columns) == RINGS_ORDER and len(df) == 2
    if STUB.exists():
        assert pq.read_schema(STUB).equals(RINGS_PA_SCHEMA), "contract stub schema drifted from ringshield.rings"


@pytest.mark.skipif(not (SCORED.exists() and LEGACY_CSV.exists()), reason="contract / legacy files not on disk")
def test_reproduces_legacy_e7():
    """aggregate_cc on scored_edges_gine_1 (top 0.5 %, min_size 3) == legacy rings_gine.csv."""
    se = pd.read_parquet(SCORED)
    thr_legacy = threshold_for_pct(se["score_raw"].to_numpy(), 0.5)   # legacy cut was inclusive (score >= q)
    rings = aggregate_cc(se, seed_frac_pct=0.5, min_size=3, score_col="score_raw", threshold=thr_legacy)
    legacy = pd.read_csv(LEGACY_CSV)
    assert list(legacy.columns) == E7_RING_CSV_COLUMNS
    assert len(rings) == len(legacy) == 178
    got = {tuple(r.members): r for r in rings}
    for row in legacy.itertuples(index=False):
        key = tuple(sorted(int(x) for x in str(row.members).split("|")))
        assert key in got, f"legacy ring {row.ring_idx} not produced"
        r = got[key]
        assert r.n_members == row.n_members and r.n_edges == row.n_edges
        assert round(r.confidence, 4) == pytest.approx(row.confidence, abs=1e-4)
        assert round(r.max_edge_prob, 4) == pytest.approx(row.max_edge_prob, abs=1e-4)
        assert round(r.density, 4) == pytest.approx(row.density, abs=1e-4)
        assert r.start_time == row.start_time + OFFSET and r.end_time == row.end_time + OFFSET
        assert round(r.duration_hours, 2) == pytest.approx(row.duration_hours, abs=1e-2)
    # member / seed edge semantics against a brute-force isin() on five rings
    from_id, to_id, ts, eid = (se[c].to_numpy(np.int64) for c in ("from_id", "to_id", "timestamp", "edge_id"))
    thr = threshold_for_pct(se["score_raw"].to_numpy(), 0.5)
    flagged = se["score_raw"].to_numpy() >= thr
    for r in rings[:3] + rings[-2:]:
        m = np.asarray(r.members)
        sel = np.isin(from_id, m) & np.isin(to_id, m) & (ts >= r.start_time) & (ts <= r.end_time)
        assert sorted(r.member_edges) == sorted(eid[sel].tolist())
        assert sorted(r.seed_edges) == sorted(eid[sel & flagged].tolist())
        assert set(r.seed_edges) <= set(r.member_edges)
    n_seed_total = sum(len(r.seed_edges) for r in rings)
    assert n_seed_total <= int(flagged.sum())
    print(f"\n[legacy] 178 rings reproduced; seed_edges {n_seed_total:,} of {int(flagged.sum()):,} thresholded edges, "
          f"member_edges {sum(len(r.member_edges) for r in rings):,}")


@pytest.mark.skipif(not (GT.exists() and TEST_PQ.exists()), reason="processed data not on disk")
def test_truth_moved_unchanged():
    t_min, t_max = split_window(TEST_PQ)
    for policy, n in (("test_visible", 183), ("strict", 86), ("majority", 120)):
        truth, patterns = load_ground_truth(GT, t_min, t_max, policy, verbose=False)
        assert len(truth) == n, (policy, len(truth))
        assert set(patterns) == set(truth)


@pytest.mark.skipif(not (LEGACY_PREDS.exists() and GT.exists() and PY.exists()), reason="legacy inputs not on disk")
def test_cli_wrapper_unchanged(tmp_path):
    out = tmp_path / "rings.csv"
    cmd = [str(PY), str(REPO_ROOT / "models" / "ring_aggregator.py"), "--preds", str(LEGACY_PREDS), "--ring-gt", str(GT),
           "--out", str(out), "--top-pct", "0.5", "--min-size", "3", "--scope", "strict"]
    res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr[-2000:]
    got = pd.read_csv(out)
    legacy = pd.read_csv(LEGACY_CSV)
    assert list(got.columns) == E7_RING_CSV_COLUMNS and len(got) == len(legacy)
    key = lambda df: df.assign(k=df["members"].map(lambda s: tuple(sorted(int(x) for x in s.split("|"))))).set_index("k")
    g, l = key(got), key(legacy)
    assert set(g.index) == set(l.index)
    l = l.loc[g.index]
    for c in ("n_members", "n_edges", "start_time", "end_time"):
        assert (g[c].values == l[c].values).all(), c
    for c in ("confidence", "max_edge_prob", "density", "duration_hours"):
        assert np.allclose(g[c].values, l[c].values, atol=1e-4), c
    meta = pd.read_json(out.with_suffix(".metrics.json"), typ="series")
    assert meta["n_predicted"] == 178 and meta["n_truth"] == 86 and meta["aggregator"].endswith("aggregate_cc")
