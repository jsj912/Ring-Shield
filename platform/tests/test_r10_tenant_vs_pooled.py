from __future__ import annotations

from pathlib import Path
import sys

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from adapters.experiment_metrics import bootstrap_ring_metrics, ring_level_summary
from experiments.r10_tenant_vs_pooled import tenant_truth_ids


def test_cross_bank_truth_ring_is_in_tenant_subset_and_pooled_finds_its_extra_recall():
    truth = {100: {11, 12}, 200: {21, 22}}
    bank_membership = {100: {210, 220}, 200: {220}}
    tenant_truth = {ring_id: truth[ring_id]
                    for ring_id in tenant_truth_ids(bank_membership, 210)}
    assert list(tenant_truth) == [100]

    tenant_metrics = ring_level_summary([], tenant_truth)
    pooled_metrics = ring_level_summary([{11, 12}], tenant_truth)
    assert tenant_metrics["ring_recall"] == 0.0
    assert pooled_metrics["ring_recall"] == 1.0
    assert pooled_metrics["ring_recall"] - tenant_metrics["ring_recall"] == 1.0


def test_r10_bootstrap_is_seeded_over_one_thousand_truth_ring_resamples():
    truth = {1: {1, 2}, 2: {3, 4}, 3: {5, 6}}
    predicted = [{1, 2}, {5}]
    first = bootstrap_ring_metrics(predicted, truth, seed=99)
    second = bootstrap_ring_metrics(predicted, truth, seed=99)
    assert first == second
    assert first["ring_recall"]["low"] <= 2 / 3 <= first["ring_recall"]["high"]
