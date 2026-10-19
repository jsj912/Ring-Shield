"""Validation helpers for keeping retraining labels out of evaluation metrics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


class TrainingEvaluationError(ValueError):
    """A training/evaluation overlap or version provenance error."""


def _ring_ids(values: Any, *, field: str) -> set[str]:
    if not isinstance(values, list):
        raise TrainingEvaluationError(f"{field} must be a list of ring IDs")
    if any(value is None or isinstance(value, (dict, list, bool)) for value in values):
        raise TrainingEvaluationError(f"{field} contains an invalid ring ID")
    ids = [str(value) for value in values]
    if len(ids) != len(set(ids)):
        raise TrainingEvaluationError(f"{field} contains duplicate ring IDs")
    return set(ids)


def training_ring_ids_from_version(version: dict[str, Any]) -> set[str]:
    """Read the training-ring provenance from the research CLI version contract."""
    if version.get("retrained") is False:
        return set()
    training = version.get("training_labels")
    if not isinstance(training, dict) or "rings" not in training:
        raise TrainingEvaluationError(
            "retrained version.json must declare training_labels.rings"
        )
    return _ring_ids(training["rings"], field="training_labels.rings")


def training_ring_ids_from_path(version_path: Path) -> set[str]:
    try:
        version = json.loads(Path(version_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingEvaluationError("model version.json is missing or invalid") from exc
    if not isinstance(version, dict):
        raise TrainingEvaluationError("model version.json must contain an object")
    return training_ring_ids_from_version(version)


def validate_labels_disjoint_from_holdout(
        labels: list[dict[str, Any]], *, holdout_ring_ids: Iterable[Any],
        validation_edge_ids: set[int]) -> None:
    """Reject label ring IDs in the holdout or member edges from val days 6–7."""
    holdout_ids = {str(value) for value in holdout_ring_ids}
    for row in labels:
        ring_id = str(row["ring_id"])
        if ring_id in holdout_ids:
            raise TrainingEvaluationError(
                f"training label ring {ring_id} overlaps the holdout ring IDs"
            )
        edges = row.get("member_edges") or []
        overlap = sorted(set(map(int, edges)) & validation_edge_ids)
        if overlap:
            raise TrainingEvaluationError(
                f"training label ring {ring_id} contains validation-window edge IDs"
            )


def make_evaluation_manifest(*, truth_ring_ids: Iterable[Any],
                             predicted_ring_ids: Iterable[Any],
                             excluded_ring_ids: set[str]) -> dict[str, list[Any]]:
    """Return deterministic truth/prediction allowlists excluding training rings."""
    def sort_key(value: Any) -> tuple[int, int | str]:
        text = str(value)
        try:
            return (0, int(text))
        except ValueError:
            return (1, text)

    truth = [value for value in truth_ring_ids if str(value) not in excluded_ring_ids]
    predicted = sorted({str(value) for value in predicted_ring_ids
                        if str(value) not in excluded_ring_ids}, key=sort_key)
    return {"truth_ring_ids": sorted(truth, key=sort_key),
            "pred_ring_ids": predicted}
