from __future__ import annotations

import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import numpy as np

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs import build_tenant_rings as job


def _scores(path: Path):
    pq.write_table(pa.table({
        "edge_id": pa.array([1, 2, 3, 4], type=pa.int64()),
        "from_bank": pa.array([10, 20, 10, 30], type=pa.int64()),
        "to_bank": pa.array([20, 10, 11, 40], type=pa.int64()),
        "score_raw": pa.array([0.9, 0.8, 0.7, 0.1]),
    }), path)


def test_build_edge_subset_includes_edges_touching_either_endpoint_bank(tmp_path):
    scores = tmp_path / "scores.parquet"
    subset = tmp_path / "out" / "tenant_10_edges.parquet"
    _scores(scores)

    count = job.build_edge_subset(scores, 10, subset)

    assert count == 3
    assert pq.read_table(subset)["edge_id"].to_pylist() == [1, 2, 3]


def test_build_edge_subset_rejects_sensitive_input_columns(tmp_path):
    scores = tmp_path / "scores.parquet"
    pq.write_table(pa.table({
        "edge_id": [1], "from_bank": [10], "to_bank": [20], "true_label": [1],
    }), scores)

    with pytest.raises(job.TenantRingBuildError, match="labels and account numbers"):
        job.build_edge_subset(scores, 10, tmp_path / "subset.parquet")


def test_ring_visibility_checks_member_seed_and_expanded_edges():
    score_by_id = {1: (0.9, 20, 10), 2: (0.5, 30, 40)}
    row = {"member_edges": [1], "seed_edges": [1], "expanded_edges": []}
    job.validate_ring_visibility(row, 10, {1}, score_by_id)
    for column in ("member_edges", "seed_edges", "expanded_edges"):
        bad = {"member_edges": [], "seed_edges": [], "expanded_edges": []}
        bad[column] = [2]
        with pytest.raises(job.TenantRingBuildError, match="outside its input subset"):
            job.validate_ring_visibility(bad, 10, {1}, score_by_id)
        with pytest.raises(job.TenantRingBuildError, match="non-visible"):
            job.validate_ring_visibility(bad, 10, {2}, score_by_id)


def test_fixed_cutoff_inversion_produces_exact_cli_percentile():
    pct = job.seed_fraction_for_cutoff(np.array([0.7, 0.8, 0.9]), 0.8)

    assert job.threshold_for_pct(np.array([0.7, 0.8, 0.9]), pct) == 0.8


def test_fixed_cutoff_above_visible_score_range_selects_no_seeds():
    scores = np.array([0.1, 0.2, 0.3])

    pct = job.seed_fraction_for_cutoff(scores, 0.4)

    assert pct == 0.0
    assert not np.any(scores > job.threshold_for_pct(scores, pct))


def test_fixed_cutoff_rounding_must_preserve_exact_seed_membership():
    scores = np.array([0.0028341208190123, 0.0236825109391033, 0.9295209672451074])
    cutoff = 0.9295209672451074

    pct = job.seed_fraction_for_cutoff(scores, cutoff)
    cli_q = job.threshold_for_pct(scores, pct)

    assert np.array_equal(scores > cli_q, scores > cutoff)


def test_build_tenant_rings_preserves_scoped_run_contract(tmp_path, monkeypatch):
    scores = tmp_path / "scores.parquet"
    _scores(scores)
    score_log_path = Path(str(scores) + ".log.json")
    score_log_path.write_text(json.dumps({
        "split": "test", "model_id": "gine_causal", "seed": 1,
        "seed_rule": {"q": 0.8},
    }), encoding="utf-8")
    model_dir = tmp_path / "model"
    (model_dir / "policy").mkdir(parents=True)
    (model_dir / "affinity").mkdir()
    (model_dir / "policy" / "policy.txt").write_text("policy", encoding="utf-8")
    (model_dir / "affinity" / "affinity.txt").write_text("affinity", encoding="utf-8")
    (model_dir / "model.json").write_text(json.dumps({
        "model_id": "gine_causal", "seed": 1, "aggregator": "full",
    }), encoding="utf-8")
    gfp = tmp_path / "gfp.parquet"
    embeddings = tmp_path / "embeddings.parquet"
    gfp.touch()
    embeddings.touch()
    output_dir = tmp_path / "runs"

    def fake_run(command, *, cwd, check):
        assert cwd == job.REPO_ROOT
        assert check is True
        tenant_id = int(command[command.index("--tenant-id") + 1])
        rings_path = Path(command[command.index("--out") + 1])
        subset_path = Path(command[command.index("--edge-subset") + 1])
        subset_ids = pq.read_table(subset_path)["edge_id"].to_pylist()
        pq.write_table(pa.table({
            "tenant_id": pa.array([tenant_id], type=pa.int64()),
            "member_edges": pa.array([subset_ids[:1]], type=pa.list_(pa.int64())),
            "seed_edges": pa.array([subset_ids[:1]], type=pa.list_(pa.int64())),
            "expanded_edges": pa.array([[]], type=pa.list_(pa.int64())),
        }), rings_path)
        log = {
            "out": str(rings_path),
            "edge_subset": str(subset_path),
            "tenant_rule": f"explicit tenant_id={tenant_id} for tenant-scoped edge subset",
            "n_edges_used": len(subset_ids), "aggregator": "full",
            "model": {"model_id": "gine_causal", "seed": 1, "aggregator": "full"},
            "params": {"seed_frac_pct": float(command[command.index("--seed-frac-pct") + 1])},
            "quantile_cut": {"q": 0.8, "n_seeds": 1},
        }
        Path(str(rings_path) + ".log.json").write_text(json.dumps(log), encoding="utf-8")

    monkeypatch.setattr(job.subprocess, "run", fake_run)

    results = job.build_tenant_rings(
        scores_path=scores, model_dir=model_dir, gfp_path=gfp,
        embeddings_path=embeddings, tenant_ids=[10], output_dir=output_dir,
        config={
            "active_model_id": "gine_causal", "active_seed": 1,
            "seed_score_cutoff": 0.8,
            "seed_score_cutoff_source": f"{score_log_path}:seed_rule.q",
            "seed_score_column": "score_raw",
        },
    )

    assert results[0]["tenant_id"] == 10
    assert results[0]["visible_edges"] == 3
    assert results[0]["rings"] == 1
    assert results[0]["seed_edges"] == 1
    assert Path(results[0]["rings_log_path"]).is_file()
    written_log = json.loads(Path(results[0]["rings_log_path"]).read_text(encoding="utf-8"))
    assert written_log["split"] == "test"
    assert written_log["platform_config"]["seed_score_cutoff"] == 0.8
