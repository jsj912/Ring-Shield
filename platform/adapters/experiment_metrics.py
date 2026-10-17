"""Research metric adapter for ring-level bootstrap confidence intervals."""

from __future__ import annotations

import numpy as np
from evaluation.ring_metrics import match_rings


def bootstrap_ring_metrics(predicted: list[set[int]], truth: dict,
                           *, seed: int, resamples: int = 1000) -> dict[str, dict[str, float]]:
    """Bootstrap truth rings using the repository's fixed one-to-one Jaccard matcher."""
    if resamples != 1000:
        raise ValueError("platform experiment confidence intervals require 1000 resamples")
    if not truth:
        return {key: {"low": 0.0, "high": 0.0}
                for key in ("ring_recall", "member_coverage")}
    matches, _, _ = match_rings(predicted, truth, threshold=0.5)
    recall_by_truth = {truth_id: 0.0 for truth_id in truth}
    coverage_by_truth = {}
    for match in matches:
        recall_by_truth[match.truth_id] = 1.0
        coverage_by_truth[match.truth_id] = float(match.coverage)
    truth_ids = list(truth)
    recall_values = np.asarray([recall_by_truth[truth_id] for truth_id in truth_ids])
    rng = np.random.default_rng(int(seed))
    recall_samples = np.empty(resamples, dtype=float)
    coverage_samples = np.empty(resamples, dtype=float)
    for index in range(resamples):
        sample = rng.integers(0, len(truth_ids), size=len(truth_ids))
        recall_samples[index] = float(np.mean(recall_values[sample]))
        matched_coverages = [coverage_by_truth[truth_ids[item]] for item in sample
                             if truth_ids[item] in coverage_by_truth]
        coverage_samples[index] = float(np.mean(matched_coverages)) if matched_coverages else 0.0
    return {
        "ring_recall": {"low": float(np.quantile(recall_samples, 0.025)),
                        "high": float(np.quantile(recall_samples, 0.975))},
        "member_coverage": {"low": float(np.quantile(coverage_samples, 0.025)),
                            "high": float(np.quantile(coverage_samples, 0.975))},
    }


def ring_level_summary(predicted: list[set[int]], truth: dict) -> dict[str, float]:
    """Return recall and matched-pair coverage from the canonical ring matcher."""
    matches, _, _ = match_rings(predicted, truth, threshold=0.5)
    return {
        "ring_recall": len(matches) / len(truth) if truth else 0.0,
        "member_coverage": (sum(float(match.coverage) for match in matches) / len(matches)
                            if matches else 0.0),
    }
