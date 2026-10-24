from __future__ import annotations

from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs.training_evaluation import (TrainingEvaluationError, make_evaluation_manifest,
                                      training_ring_ids_from_version,
                                      validate_labels_disjoint_from_holdout)


def test_label_ring_id_must_not_overlap_holdout():
    with pytest.raises(TrainingEvaluationError, match="overlaps the holdout ring IDs"):
        validate_labels_disjoint_from_holdout(
            [{"ring_id": "38", "member_edges": [1]}],
            holdout_ring_ids=[38], validation_edge_ids=set(),
        )


def test_label_edge_must_not_overlap_validation_days_six_and_seven():
    with pytest.raises(TrainingEvaluationError, match="validation-window edge IDs"):
        validate_labels_disjoint_from_holdout(
            [{"ring_id": "full-model-1-7", "member_edges": [100, 101]}],
            holdout_ring_ids=[38], validation_edge_ids={101, 102},
        )


def test_non_overlapping_label_is_allowed():
    validate_labels_disjoint_from_holdout(
        [{"ring_id": "full-model-1-7", "member_edges": [100]}],
        holdout_ring_ids=[38], validation_edge_ids={101, 102},
    )


def test_version_json_exposes_training_ring_ids_from_contract_field():
    assert training_ring_ids_from_version({
        "retrained": True, "training_labels": {"rings": ["12", "full-model-1-3"]},
    }) == {"12", "full-model-1-3"}
    assert training_ring_ids_from_version({"retrained": False}) == set()


def test_version_json_accepts_the_research_trainers_ring_records():
    """`ringshield train` writes training_labels.rings as records, not strings (R11 run, 2026-10-24)."""
    version = {"retrained": True, "training_labels": {"n_rings": 2, "rings": [
        {"ring_id": "full-gine_causal-1-0", "verdict": "reject", "n_member_edges": 4, "group_id": 1000000000},
        {"ring_id": "full-gine_causal-1-5", "verdict": "confirm", "n_member_edges": 5, "group_id": 1000000003},
    ]}}
    assert training_ring_ids_from_version(version) == {"full-gine_causal-1-0", "full-gine_causal-1-5"}
    with pytest.raises(TrainingEvaluationError, match="without a ring_id"):
        training_ring_ids_from_version({"retrained": True, "training_labels": {"rings": [
            {"ring_id": "a"}, {"verdict": "confirm"}]}})


def test_retrained_version_without_ring_provenance_is_rejected():
    with pytest.raises(TrainingEvaluationError, match="training_labels.rings"):
        training_ring_ids_from_version({"retrained": True, "labels": "labels.parquet"})


def test_eval_manifest_excludes_trained_ring_from_both_sides():
    manifest = make_evaluation_manifest(
        truth_ring_ids=[12, 38, 104],
        predicted_ring_ids=["full-model-1-0", "full-model-1-1", "other"],
        excluded_ring_ids={"38", "full-model-1-1"},
    )

    assert manifest == {
        "truth_ring_ids": [12, 104],
        "pred_ring_ids": ["full-model-1-0", "other"],
    }
