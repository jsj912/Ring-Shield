from __future__ import annotations

import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs.load_explanations import ExplanationLoadError, read_handoff

pytestmark = pytest.mark.usefixtures("repo_platform_config")


def _files(tmp_path, *, reproduced=True, tenant_scope=True):
    provenance = {
        "aggregator_id": "full", "model_id": "gine_causal", "seed": 1,
        "rings_schema_version": 2, "explainer_version": "0.4.0-narrative",
        "loo": {"reproduces_shipped_ring": reproduced},
    }
    row = {
        "ring_id": "full-gine_causal-1-0", "tenant_id": 135981,
        "edge_weights": [{"edge_id": 17, "w_total": 0.8}],
        "account_weights": [{"account_id": 21, "role": "source", "w_account": 1.0,
                             "hold_time_s": float("nan")}],
        "feature_weights": [{"feature_name": "Payment Format", "mean_shap": 0.5,
                             "top_edge_id": 17}],
        "topology_type": "FAN-OUT", "topology_prob": 0.7,
        "narrative": "Example ring", "evidence_summary": json.dumps({"template": "FAN-OUT"}),
        "latency_ms": 25, "provenance": json.dumps(provenance),
    }
    parquet_path = tmp_path / "explanations.parquet"
    pq.write_table(pa.Table.from_pylist([row]), parquet_path)
    log_path = Path(str(parquet_path) + ".log.json")
    log_path.write_text(json.dumps({
        "split": "test",
        "inputs": {"rings": "rings_tenant_135981.parquet"},
        "explainer_version": "0.4.0-narrative", "n_explained": 1, "n_rings": 1,
        "n_reproduces_shipped_ring": int(reproduced),
        "not_reproduced": [] if reproduced else [row["ring_id"]],
        "policy": "converted",
        "provenance": {"aggregator_id": "full", "model_id": "gine_causal",
                       "seed": 1, "rings_schema_version": 2},
    }), encoding="utf-8")
    rings_log_path = tmp_path / "rings_tenant_135981.parquet.log.json"
    rings_log_path.write_text(json.dumps({
        "split": "test",
        "command": "run",
        "edge_subset": "tenant_135981_edges.parquet" if tenant_scope else None,
        "tenant_rule": ("explicit tenant_id=135981 for tenant-scoped edge subset"
                        if tenant_scope else "sender bank of earliest seed edge"),
        "aggregator": "full",
        "model": {"model_id": "gine_causal", "seed": 1, "aggregator": "full"},
        "out": "rings_tenant_135981.parquet",
    }), encoding="utf-8")
    return parquet_path, log_path, rings_log_path


def test_read_handoff_converts_json_and_nonfinite_values(tmp_path):
    parquet_path, log_path, rings_log_path = _files(tmp_path)

    rows, log = read_handoff(parquet_path, log_path, rings_log_path)

    assert log["explainer_version"] == "0.4.0-narrative"
    assert rows[0]["evidence_summary"] == {"template": "FAN-OUT"}
    assert rows[0]["account_weights"][0]["hold_time_s"] is None
    assert rows[0]["provenance"]["loo"]["reproduces_shipped_ring"] is True


def test_read_handoff_rejects_stub_or_nonreproduced_batch(tmp_path):
    parquet_path, log_path, rings_log_path = _files(tmp_path, reproduced=False)

    with pytest.raises(ExplanationLoadError, match="do not reproduce"):
        read_handoff(parquet_path, log_path, rings_log_path)


def test_read_handoff_rejects_unreproduced_per_row_provenance(tmp_path):
    parquet_path, log_path, rings_log_path = _files(tmp_path)
    table = pq.read_table(parquet_path).to_pylist()
    table[0]["provenance"] = json.dumps({
        "aggregator_id": "full", "model_id": "gine_causal", "seed": 1,
        "rings_schema_version": 2, "explainer_version": "0.4.0-narrative",
        "loo": {"reproduces_shipped_ring": False},
    })
    pq.write_table(pa.Table.from_pylist(table), parquet_path)

    with pytest.raises(ExplanationLoadError, match="does not confirm ring reproduction"):
        read_handoff(parquet_path, log_path, rings_log_path)


def test_read_handoff_rejects_global_ring_run(tmp_path):
    parquet_path, log_path, rings_log_path = _files(tmp_path, tenant_scope=False)

    with pytest.raises(ExplanationLoadError, match="tenant-scoped run"):
        read_handoff(parquet_path, log_path, rings_log_path)
