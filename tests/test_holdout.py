"""The held-out-pattern contract (Step 11 / R7, check 1).

A holdout must do exactly three things and no more:
  * relabel the pattern's edges licit in **train and val**, never in test;
  * remove its rings from every ring-label set a stage trains on;
  * leave the graph, the candidate pool and the scored-edge tables untouched.

The tests below check the helper on a fixture (so they run without any artefact on disk) and, when
the real parquets are present, that the holdout the pipeline would apply is the one the split
parquets describe. `test_no_heldout_label_survives_a_training_table` is the assertion the step
requires: it is what every training entry point calls before writing its table.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ringshield.holdout import TRAINING_SPLITS, Holdout  # noqa: E402

PATTERN = "BIPARTITE"
PROCESSED = REPO_ROOT / "data" / "processed"


def fixture_holdout() -> Holdout:
    """Two held-out rings (101, 102) with edges 10-13, and one kept ring (201) with edges 20-21."""
    return Holdout(pattern=PATTERN, ring_ids={101, 102},
                   edges_by_split={"train": {10, 11}, "val": {12}, "test": {13}})


# --------------------------------------------------------------------------- the helper
def test_inactive_holdout_is_a_no_op():
    ho = Holdout.load(None)
    assert not ho.is_active and ho.summary() == {"hold_out_pattern": None}
    df = pd.DataFrame({"ring_id": [1, 2], "label": [1, 0]})
    assert ho.drop_rings(df).equals(df)
    y = np.array([1, 1, 0])
    assert (ho.relabel_licit([10, 11, 12], y) == y).all()
    ho.assert_absent(df, ring_col="ring_id", label_col="label")      # never raises


def test_relabel_touches_train_and_val_but_not_test():
    ho = fixture_holdout()
    edge_ids = np.array([10, 11, 12, 13, 99])       # train, train, val, test, unrelated
    y = np.array([1, 1, 1, 1, 1])
    out = ho.relabel_licit(edge_ids, y, splits=TRAINING_SPLITS)
    assert out.tolist() == [0, 0, 0, 1, 1], "test labels and unrelated edges must be untouched"
    assert y.tolist() == [1, 1, 1, 1, 1], "the input array must not be modified in place"


def test_relabel_can_be_asked_for_every_split():
    ho = fixture_holdout()
    out = ho.relabel_licit(np.array([10, 12, 13]), np.array([1, 1, 1]), splits=("train", "val", "test"))
    assert out.tolist() == [0, 0, 0]


def test_drop_rings_removes_only_held_out_rings():
    ho = fixture_holdout()
    df = pd.DataFrame({"ring_id": [101, 102, 201, -1], "x": [1, 2, 3, 4]})
    out = ho.drop_rings(df)
    assert out["ring_id"].tolist() == [201, -1] and out["x"].tolist() == [3, 4]


def test_keep_rings_preserves_order():
    assert fixture_holdout().keep_rings([201, 101, 202, 102]) == [201, 202]


# --------------------------------------------------------------------------- the assertion
def test_no_heldout_label_survives_a_training_table():
    """The check the step requires: a held-out ring id or a positive held-out label must raise."""
    ho = fixture_holdout()
    clean = pd.DataFrame({"ring_id": [201, -1], "candidate_edge_id": [20, 21], "label": [1, 0]})
    ho.assert_absent(clean, ring_col="ring_id", label_col="label", edge_col="candidate_edge_id")

    with pytest.raises(AssertionError, match="held-out BIPARTITE ring id"):
        ho.assert_absent(pd.DataFrame({"ring_id": [101], "label": [1]}), ring_col="ring_id")

    with pytest.raises(AssertionError, match="carry a positive label"):
        ho.assert_absent(pd.DataFrame({"ring_id": [-1], "candidate_edge_id": [10], "label": [1]}),
                         ring_col="ring_id", label_col="label", edge_col="candidate_edge_id")

    # a held-out edge with a zero label is exactly what a relabelled training row looks like
    ho.assert_absent(pd.DataFrame({"ring_id": [-1], "candidate_edge_id": [10], "label": [0]}),
                     ring_col="ring_id", label_col="label", edge_col="candidate_edge_id")


def test_unknown_pattern_is_rejected():
    if not (PROCESSED / "amlworld_train.parquet").exists():
        pytest.skip("split parquets not on disk")
    with pytest.raises(AssertionError, match="does not occur"):
        Holdout.load("NOT-A-PATTERN")


# --------------------------------------------------------------------------- against the real data
@pytest.mark.parametrize("pattern", ["BIPARTITE", "CYCLE"])
def test_real_holdout_matches_the_split_parquets(pattern):
    if not (PROCESSED / "amlworld_train.parquet").exists():
        pytest.skip("split parquets not on disk")
    ho = Holdout.load(pattern)
    assert ho.is_active and ho.ring_ids
    for split in ("train", "val", "test"):
        df = pd.read_parquet(PROCESSED / f"amlworld_{split}.parquet",
                             columns=["EdgeID", "ring_id", "pattern_type"])
        expect = set(df.loc[(df["ring_id"] > 0) & (df["pattern_type"] == pattern), "EdgeID"].tolist())
        assert ho.edges_by_split[split] == expect, f"{split}: edge set differs from the parquet"
    # no ring may carry two pattern types, or "held out" would be ambiguous
    all_rows = pd.concat([pd.read_parquet(PROCESSED / f"amlworld_{s}.parquet", columns=["ring_id", "pattern_type"])
                          for s in ("train", "val", "test")])
    held = all_rows[all_rows["ring_id"].isin(ho.ring_ids)]
    assert (held["pattern_type"] == pattern).all(), "a held-out ring carries another pattern type"


def test_training_splits_exclude_test():
    assert "test" not in TRAINING_SPLITS, "test labels are the measurement and must never be held out"
