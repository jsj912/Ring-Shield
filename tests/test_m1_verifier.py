"""M1 leak guards (paper/PREREG_METHOD_2026-11-15.md §2, amendments 1-2).

Unit tests run anywhere; the integration tests read experiments/M1_verifier/candidates/train/seed1
and skip when it has not been built yet.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from evaluation import m1_verifier as m1
from evaluation.ring_metrics import match_rings

TRAIN = m1.OUT / "candidates" / "train" / "seed1"


def test_primary_excludes_in_sample_features():
    allf = ["n_members", "q_mean", *m1.IS_FEATURES]
    prim = [c for c in allf if c not in m1.IS_FEATURES]
    assert not set(prim) & {"exp_prob_mean", "exp_prob_min", "exp_prob_count", "confidence", "max_edge_prob"}
    assert "mean_raw_score" in m1.BOOK and "label" in m1.BOOK      # never a verifier feature


def test_recording_store_logs_missing_and_returns_known_rows():
    from ringshield.expand.features import EmbeddingStore
    base = EmbeddingStore(np.array([3, 7]), np.array([[1.0, 2.0], [3.0, 4.0]]))
    st = m1.RecordingStore(base, 2)
    out = st.get([7, 5, 3])
    assert out.tolist() == [[3.0, 4.0], [0.0, 0.0], [1.0, 2.0]]
    assert st.missing == {5}


def test_labels_ignore_rings_outside_the_truth_dict():
    """A label is 1 only through a match against the train truth passed in; a val/test ring that is
    not in that dict can never create a positive, even if a candidate equals it exactly."""
    preds = [{1, 2, 3}, {10, 11, 12}]
    train_truth = {101: {1, 2, 3}}
    val_ring = {10, 11, 12}
    m, _, _ = match_rings(preds, train_truth, 0.5)
    lab = np.zeros(2, int)
    for x in m:
        lab[x.pred_idx] = 1
    m2, _, _ = match_rings(preds, {**train_truth, 999: val_ring}, 0.5)
    assert lab.tolist() == [1, 0]
    assert len(m2) == 2      # injecting the val ring WOULD change a label -> the truth source must be train-only


def test_train_truth_is_train_window_only():
    from contract.make_scored_edges import load_paths
    from ringshield.truth import load_ground_truth, split_window
    pdir = load_paths()["processed_dir"]
    lo, hi = split_window(pdir / "amlworld_train.parquet")
    truth, _ = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", lo, hi, "test_visible", verbose=False)
    tr = pd.read_parquet(pdir / "amlworld_train.parquet", columns=["ring_id", "from_id", "to_id", "Timestamp"])
    assert tr["Timestamp"].max() <= hi and (tr["Timestamp"].max() - 10) // 86400 <= 5
    acc = {r: set(g["from_id"]) | set(g["to_id"]) for r, g in tr[tr["ring_id"] > 0].groupby("ring_id")}
    assert set(truth) == set(acc)                       # every label ring is a train ring ...
    assert all(truth[r] == acc[r] for r in truth)       # ... with train-visible members only


def test_owner_fold_rule_matches_cross_scores():
    rf = pd.read_parquet(m1.XS / "ring_folds.parquet")
    xs = pd.read_parquet(m1.XS / "cross_scores_train.parquet", columns=["edge_id", "fold", "day"]).set_index("edge_id")
    assert (xs["fold"].reindex(rf["edge_id"]).to_numpy() == rf["fold"].to_numpy()).all()
    non_ring = xs.drop(index=rf["edge_id"], errors="ignore")
    day_fold = {0: 0, 1: 1, 2: 2, 3: 2, 4: 3, 5: 4}
    assert (non_ring["fold"].to_numpy() == non_ring["day"].map(day_fold).to_numpy()).all()


@pytest.mark.skipif(not (TRAIN / "rings.parquet").exists(), reason="train candidates not built")
def test_train_candidates_are_train_period_and_labelled_from_train():
    from contract.make_scored_edges import load_paths
    from ringshield.rings import read_rings_parquet
    pdir = load_paths()["processed_dir"]
    rings = read_rings_parquet(TRAIN / "rings.parquet")
    feats = pd.read_parquet(TRAIN / "features.parquet")
    tr = pd.read_parquet(pdir / "amlworld_train.parquet", columns=["EdgeID", "Timestamp"]).set_index("EdgeID")["Timestamp"]
    for r in rings:
        ts = tr.reindex(r.member_edges)
        assert ts.notna().all(), "a candidate uses an edge outside the train split"
        assert int(((ts - 10) // 86400).max()) <= 5
    assert len(feats) == len(rings) and set(feats["label"].unique()) <= {0, 1}
    meta = json.loads((TRAIN / "meta.json").read_text(encoding="utf-8"))
    assert meta["split"] == "train" and meta["n_pos"] == int(feats["label"].sum())
