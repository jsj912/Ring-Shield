from __future__ import annotations

import csv

from jobs import experiment_worker


def test_r10_dashboard_results_returns_only_tenant_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment_worker, "REPO_ROOT", tmp_path)
    result_file = tmp_path / "r10_table.csv"
    rows = [
        {
            "tenant_id": "210", "seed": "1", "n_truth_rings": "9",
            "tenant_ring_recall": "0.8", "tenant_ring_recall_ci_low": "0.7",
            "tenant_ring_recall_ci_high": "0.9", "tenant_member_coverage": "0.6",
            "pooled_ring_recall": "0.75", "pooled_ring_recall_ci_low": "0.65",
            "pooled_ring_recall_ci_high": "0.85", "pooled_member_coverage": "0.55",
            "tenant_truth_cross_bank_fraction": "0.4",
            "tenant_truth_mean_banks_per_ring": "1.5",
            "cross_bank_truth_fraction": "0.3", "mean_banks_per_truth_ring": "1.4",
            "pattern_group_id": "private-label",
        },
        {
            "tenant_id": "MEAN", "seed": "1", "tenant_ring_recall": "0.8",
            "pooled_ring_recall": "0.75",
        },
    ]
    with result_file.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)

    result = experiment_worker._r10_dashboard_results(str(result_file))

    assert result["table_rows"][0]["tenant_id"] == 210
    assert result["table_rows"][0]["tenant_ring_recall"] == 0.8
    assert result["table_rows"][1]["tenant_id"] == "Mean across tenants"
    assert result["recall_series"] == [{
        "tenant_id": 210, "seed": 1,
        "tenant_ring_recall": 0.8, "pooled_ring_recall": 0.75,
    }]
    assert "n_truth_rings" not in str(result)
    assert "pattern_group_id" not in str(result)
