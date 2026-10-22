"""Step 7 -- partition: pairs, affinity clustering, the 'full' aggregator and its baselines.

    python -m pytest tests/test_partition.py -q

Fixture: two 5-account rings that share one hub account. Ring X: x1 -> x2 -> H -> x3 -> x4 (a
stack through the hub H), ring Y: y1 -> y2 -> H -> y3 -> y4, one day later. All eight edges are
seeds, so the expanded component is one blob of 9 accounts; the proposed partition must give two
rings with Jaccard 1.0 against {x1..x4, H} and {y1..y4, H}, plain components (B2) give one.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ringshield.aggregators.full import METHODS, aggregate_full, component_pairs, included_from_trajectories, partition_labels  # noqa: E402
from ringshield.expand.features import FeatureContext  # noqa: E402
from ringshield.expand.policy import Policy  # noqa: E402
from ringshield.partition.affinity import Affinity, cluster_average, cluster_pivot, train_affinity  # noqa: E402
from ringshield.partition.pairs import KEY_COLUMNS, PAIR_FEATURES, account_roles, components_of, pair_features  # noqa: E402

H = 3600
HUB = 50
X = [1, 2, 3, 4]
Y = [11, 12, 13, 14]
DAY = 24 * H


def two_rings_frame() -> pd.DataFrame:
    rows = []
    eid = 100
    for base, accs in ((0, X), (DAY, Y)):
        chain = [accs[0], accs[1], HUB, accs[2], accs[3]]
        amt = 10000.0
        for k in range(4):
            rows.append((eid, chain[k], chain[k + 1], 1, 1, base + 10 * H + 2 * H * k, amt, amt))
            eid += 1
            amt -= 10
    # licit background at the hub and elsewhere
    rows += [(200, 60, HUB, 1, 1, 5 * H, 40.0, 40.0), (201, HUB, 61, 1, 1, 30 * H, 55.0, 55.0), (202, 70, 71, 1, 1, 12 * H, 20.0, 20.0)]
    df = pd.DataFrame(rows, columns=["edge_id", "from_id", "to_id", "from_bank", "to_bank", "timestamp", "amount_sent", "amount_received"])
    for c in ("currency_sent", "currency_received", "payment_format"):
        df[c] = 0
    df["score_raw"] = np.where(df["edge_id"] < 200, 0.9, 0.05)
    df["score_calibrated"] = df["score_raw"]
    return df.sort_values("edge_id").reset_index(drop=True)


class ChainAffinity(Affinity):
    """Stub affinity: two edges at the same account belong together iff one flows in and the other
    out within 12 h with matching amounts (the on-chain flag); everything else is 'different'."""

    def __init__(self):
        super().__init__(PAIR_FEATURES)

    def predict(self, P):
        ok = (P["on_chain"] == 1) & (P["time_gap_s"] <= 12 * H)
        return np.where(ok, 0.95, 0.05)


def _setup():
    df = two_rings_frame()
    ctx = FeatureContext.build(df)
    return df, ctx


def test_pairs_of_the_hub_component():
    df, ctx = _setup()
    inc_pos = np.flatnonzero(df["edge_id"] < 200)
    is_seed = np.ones(len(inc_pos), bool)
    comp = components_of(ctx.idx, inc_pos)
    assert (comp == 0).all()                                   # one blob through the hub
    P = pair_features(ctx.idx, ctx.gfp, inc_pos, is_seed, comp)
    assert list(P.columns) == KEY_COLUMNS + PAIR_FEATURES
    hub = P[P["shared_account"] == HUB]
    assert len(hub) == 6                                       # C(4, 2): x2->H, H->x3, y2->H, H->y3
    on = hub[hub["on_chain"] == 1]
    # x2->H then H->x3, y2->H then H->y3, and x2->H (12 h) then H->y3 (38 h): 26 h < 72 h hold, amounts match
    assert set(map(tuple, on[["edge_a", "edge_b"]].to_numpy())) == {(101, 102), (105, 106), (101, 106)}
    assert (hub["role_mule"] == 1).all() and hub["acc_n_included"].eq(4).all()
    assert (P["cos_emb"].isna()).all() and P["cos_gfp"].between(0, 1).all()
    roles = account_roles(ctx.idx, inc_pos, comp)
    assert roles.loc[(0, ctx.idx.dense([HUB])[0]), "role"] == "mule"
    assert roles.loc[(0, ctx.idx.dense([1])[0]), "role"] == "source" and roles.loc[(0, ctx.idx.dense([4])[0]), "role"] == "sink"


def test_fixture_two_rings_through_a_hub_and_b2_gives_one():
    df, ctx = _setup()
    kw = dict(policy=Policy.rule("rule"), ctx=ctx, p_min=1.0, delta_t_h=1e-6, affinity=ChainAffinity(), seed_frac_pct=80.0, min_size=3)
    # the rule policy with a vanishing window adds nothing: the expanded subgraph is the eight seeds
    b2 = aggregate_full(df, method="b2", **kw)
    assert len(b2) == 1 and b2[0].n_members == 9
    for method, extra in (("pivot", {}), ("average", {"cut": 0.5})):
        rings = aggregate_full(df, method=method, **extra, **kw)
        sets = sorted(sorted(r.members) for r in rings)
        assert sets == [sorted(X + [HUB]), sorted(Y + [HUB])], method
        for r in rings:
            truth = set(X + [HUB]) if 1 in r.members else set(Y + [HUB])
            assert len(set(r.members) & truth) / len(set(r.members) | truth) == 1.0
            assert len(r.seed_edges) == 4 and r.expanded_edges == [] and r.aggregator_id == "full"
            assert set(r.seed_edges) <= set(r.member_edges)
    # B3 with a 12 h gap also separates the two days; B4 (Louvain on the affinity-weighted account graph) too
    b3 = aggregate_full(df, method="b3", gap_h=12, **kw)
    assert sorted(sorted(r.members) for r in b3) == [sorted(X + [HUB]), sorted(Y + [HUB])]
    # B4 (Louvain on the affinity-weighted account graph, a tree here) over-fragments -- modularity on a
    # path splits it into 2-3 node communities -- but it never mixes the two rings
    b4 = aggregate_full(df, method="b4", seed=0, **kw)
    assert b4 and all(not (set(r.members) & set(X) and set(r.members) & set(Y)) for r in b4)


def test_clustering_is_deterministic_across_runs():
    df, ctx = _setup()
    kw = dict(policy=Policy.rule("rule"), ctx=ctx, p_min=1.0, delta_t_h=1e-6, affinity=ChainAffinity(), seed_frac_pct=80.0, min_size=3)
    a = [r.to_dict() for r in aggregate_full(df, method="pivot", seed=3, **kw)]
    b = [r.to_dict() for r in aggregate_full(df, method="pivot", seed=3, **kw)]
    assert a == b
    c = [r.to_dict() for r in aggregate_full(df, method="average", cut=0.5, **kw)]
    d = [r.to_dict() for r in aggregate_full(df, method="average", cut=0.5, **kw)]
    assert c == d
    # random pairs: identical labels twice, and a relabelling-invariant partition across pivot seeds
    rng = np.random.default_rng(0)
    n = 40
    ia, ib = rng.integers(0, n, 300), rng.integers(0, n, 300)
    p = rng.random(300)
    l1, l2 = cluster_pivot(n, ia, ib, p, seed=1), cluster_pivot(n, ia, ib, p, seed=1)
    assert np.array_equal(l1, l2)
    l3 = cluster_pivot(n, ia, ib, p, seed=7)
    assert len({frozenset(np.flatnonzero(l1 == k)) for k in np.unique(l1)}) == len({frozenset(np.flatnonzero(l3 == k)) for k in np.unique(l3)})
    assert np.array_equal(cluster_average(n, ia, ib, p, cut=0.5), cluster_average(n, ia, ib, p, cut=0.5))


def test_average_linkage_keeps_chains_and_cuts_weak_links():
    # chain e0-e1-e2-e3 with strong links, e3-e4 weak
    ia, ib = np.array([0, 1, 2, 3]), np.array([1, 2, 3, 4])
    p = np.array([0.9, 0.9, 0.9, 0.2])
    lab = cluster_average(5, ia, ib, p, cut=0.5)
    assert lab[0] == lab[1] == lab[2] == lab[3] != lab[4]
    lab = cluster_pivot(5, ia, ib, p, seed=0)
    assert lab[0] == lab[1] == lab[2] == lab[3] != lab[4]


def test_affinity_train_save_load(tmp_path):
    rng = np.random.default_rng(0)
    n = 800
    P = pd.DataFrame(rng.normal(size=(n, len(PAIR_FEATURES))), columns=PAIR_FEATURES)
    P["component"] = rng.integers(0, 40, n)
    P["label"] = ((P["on_chain"] > 0.3) & (P["amount_ratio"] > -0.2)).astype(int)
    aff = train_affinity(P, verbose=False)
    aff.save(tmp_path / "aff")
    back = Affinity.load(tmp_path / "aff")
    assert np.allclose(back.predict(P.head(20)), aff.predict(P.head(20))) and back.meta["cv"]["cv_auc_pr_mean"] > 0.5


@pytest.mark.xfail(strict=True, reason="R4 hypothesis (partition raises precision over B2 on test) not met; see docs/PARTITION.md")
def test_r4_checks_on_the_runs():
    """Check 2 (no predicted ring > 100 members for the proposed method) and check 3 (precision up vs
    B2 without recall dropping by more than the seed std; mean Jaccard up), read from the runs.

    xfail(strict): check 2 holds, check 3's precision and Jaccard clauses do not on the test primary
    window -- the partition trades precision for recall there (docs/PARTITION.md). Strict, so the
    test fails again if a later change makes the hypothesis hold and the marker is forgotten."""
    import json
    runs = REPO_ROOT / "experiments" / "R4_partition" / "runs"
    if not (runs / "b2").exists():
        pytest.skip("R4 runs not on disk")

    def block(method):
        out = []
        for p in sorted((runs / method).glob("seed*/metrics.json")):
            j = json.loads(p.read_text(encoding="utf-8"))
            out.append((j["blocks"]["primary"], j["chosen"], j["val_at_chosen"]))
        return out
    b2 = block("b2")
    assert b2, "no b2 runs"
    best = {}
    for s in range(len(b2)):
        cands = [(m, block(m)[s]) for m in ("pivot", "average") if (runs / m).exists()]
        best[s] = max(cands, key=lambda mv: mv[1][2]["ring_f1"])
    prop = [best[s][1][0] for s in best]
    assert all(b["pred_size"]["max_members"] <= 100 for b in prop)                                  # check 2
    rec_std = float(np.std([b[0]["ring_recall"] for b in b2], ddof=1)) if len(b2) > 1 else 0.0
    assert np.mean([b["ring_precision"] for b in prop]) > np.mean([b[0]["ring_precision"] for b in b2])   # check 3
    assert np.mean([b[0]["ring_recall"] for b in b2]) - np.mean([b["ring_recall"] for b in prop]) <= rec_std
    assert np.mean([b["mean_jaccard"] for b in prop]) > np.mean([b[0]["mean_jaccard"] for b in b2])


def test_reattach_small_merges_fragments_below_min_size():
    from ringshield.partition.affinity import reattach_small
    # three edges in a chain a-b, b-c, c-d; the middle pair is cut -> {e0} and {e1, e2}; e0 spans 2 accounts < 3
    ia, ib, p = np.array([0, 1]), np.array([1, 2]), np.array([0.1, 0.9])
    ends = np.array([[1, 2], [2, 3], [3, 4]])
    lab = np.array([0, 1, 1])
    out = reattach_small(lab, ia, ib, p, ends, min_members=3)
    assert out[0] == out[1] == out[2]
    # a fragment with no link stays (nothing to attach to); big clusters are untouched
    out = reattach_small(np.array([0, 1, 1]), np.array([1]), np.array([2]), np.array([0.9]), ends, min_members=3)
    assert out[0] != out[1] and out[1] == out[2]
    out = reattach_small(np.array([0, 0, 1, 1]), np.array([0, 1, 2]), np.array([1, 2, 3]), np.array([0.9, 0.1, 0.9]),
                         np.array([[1, 2], [2, 3], [3, 4], [4, 5]]), min_members=3)
    assert out[0] == out[1] != out[2] == out[3]


def test_cli_export_and_run_full(tmp_path):
    """export-model from a run_partition output, then `python -m ringshield run --aggregator full` on a 2 %
    sample (skips without the R4 run on disk)."""
    import json
    import subprocess
    run_dir = REPO_ROOT / "experiments" / "R4_partition" / "runs" / "average" / "seed1"
    scores = REPO_ROOT / "contract" / "out" / "scored_edges_gine_causal_1.parquet"
    emb = REPO_ROOT / "experiments" / "R1_gine_causal" / "embeddings_test_seed1.parquet"
    gfp = REPO_ROOT / "data" / "processed" / "amlworld_gfp_features_test.parquet"
    if not (run_dir / "config.yaml").exists() or not scores.exists() or not emb.exists():
        pytest.skip("R4 average run / contract file / embeddings not on disk")
    py = REPO_ROOT / ".venv312" / "Scripts" / "python.exe"
    md = tmp_path / "model_full"
    r = subprocess.run([str(py), "-m", "ringshield", "export-model", "--run-dir", str(run_dir), "--out-model-dir", str(md)],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    doc = json.loads((md / "model.json").read_text(encoding="utf-8"))
    assert doc["aggregator"] == "full" and doc["params"]["partition"] == "average" and "cut" in doc["params"]["partition_cell"]
    assert (md / "policy" / "policy.txt").exists() and (md / "affinity" / "affinity.txt").exists()
    se = pd.read_parquet(scores).sample(frac=0.02, random_state=1).sort_values("edge_id")
    sample = tmp_path / "sample.parquet"
    se.to_parquet(sample, index=False)
    out = tmp_path / "rings.parquet"
    r = subprocess.run([str(py), "-m", "ringshield", "run", "--scores", str(sample), "--model-dir", str(md), "--aggregator", "full",
                        "--gfp", str(gfp), "--embeddings", str(emb), "--out", str(out)], cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    from ringshield.rings import read_rings_parquet
    rings = read_rings_parquet(out)
    log = json.loads(Path(str(out) + ".log.json").read_text(encoding="utf-8"))
    assert log["aggregator"] == "full" and log["partition"] == "average"
    ids = set(se["edge_id"])
    for ring in rings:
        assert ring.aggregator_id == "full" and ring.ring_id.startswith("full-gine_causal-1-") and ring.n_members >= 3
        assert set(ring.seed_edges) <= ids and set(ring.expanded_edges) <= ids and set(ring.seed_edges) <= set(ring.member_edges)


def test_full_runs_without_a_detector_checkpoint(tmp_path):
    """A detector with no model_best_seed<S>.pt (gfpxgb is XGBoost) must still build a context:
    dead_region is simply empty instead of raising. Guards run_partition.py / run_expand.py."""
    r1 = REPO_ROOT / "experiments" / "R1_gine_causal"
    if not (r1 / "scores_test_seed1.parquet").exists():
        pytest.skip("R1 scores not on disk")
    fake = tmp_path / "no_checkpoint"
    fake.mkdir()
    for split in ("val", "test"):
        shutil.copy2(r1 / f"scores_{split}_seed1.parquet", fake / f"scores_{split}_seed1.parquet")
    assert not (fake / "model_best_seed1.pt").exists()
    from ringshield.partition import run_partition
    run_partition.main(["--seed", "1", "--method", "average", "--r1-dir", str(fake),
                        "--out", str(tmp_path / "run"), "--dry-run"])
    cfg = yaml.safe_load((tmp_path / "run" / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["dry_run"] is True


def test_classify_maps_restricted_prediction_indices():
    """restrict_rings DROPS out-of-window predictions, so positions in the restricted list are not
    positions in `rings`. classify() must map between them; indexing the restricted list with a
    full-list index silently reads a different prediction and corrupts the over-merged /
    under-covered split (it did, until 2026-09-27)."""
    from evaluation.step9_tables import read_rings_any
    from evaluation.unmatched_rings import classify
    from ringshield.evaluate import restrict_rings
    from ringshield.scored_edges import build_scored_edges
    from ringshield.truth import load_ground_truth
    from ringshield.windows import load_windows
    from contract.make_scored_edges import load_paths

    run = REPO_ROOT / "experiments" / "R4_partition" / "runs" / "average" / "seed1" / "rings.parquet"
    scores = REPO_ROOT / "experiments" / "R1_gine_causal" / "scores_test_seed1.parquet"
    if not run.exists() or not scores.exists():
        pytest.skip("R4 average run / R1 scores not on disk")
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds,
                                        "test_visible", verbose=False)
    se = build_scored_edges(scores, "test", model_id="gine_causal", seed=1, processed_dir=pdir)
    rings = read_rings_any(run)
    pred = restrict_rings(rings, se, W)
    assert len(pred) < len(rings), "fixture no longer exercises the mismatch"

    kl = classify(rings, se, truth, patterns, W)
    assert len(kl) == len(truth)
    assert set(kl["klass"]) <= {"matched", "a_lt3_members", "b_untouched", "c_over_merged", "c_under_covered"}
    # every c_* ring must have a real overlap with some restricted prediction
    for _, row in kl[kl["klass"].str.startswith("c_")].iterrows():
        assert 0.0 < row["best_jaccard"] < 0.5, f"ring {row['ring_id']}: best_jaccard {row['best_jaccard']}"
