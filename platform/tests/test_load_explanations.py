from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs.load_explanations import ExplanationLoadError, read_handoff

pytestmark = pytest.mark.usefixtures("repo_platform_config")

FX_HASH = "ee0e8a23b6037e4aeceb44b6874a70d7b46114559551fd2cf94a3842bb8d4ac6"


def _files(tmp_path, *, reproduced=True, tenant_scope=True, log_updates=None,
           row_updates=None, rings_updates=None, pooled=False):
    provenance = {
        "aggregator_id": "full", "model_id": "gine_causal", "seed": 1,
        "rings_schema_version": 2, "explainer_version": "0.4.0-narrative",
        "currency_policy": "converted", "scope": "tenant", "tenant_id": 135981,
        "feature_scope": "tenant_view", "fx_rates_sha256": FX_HASH,
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
    row.update(row_updates or {})
    rings_log_path = tmp_path / "rings_tenant_135981.parquet.log.json"
    rings_path = tmp_path / "rings_tenant_135981.parquet"
    rings_path.write_bytes(b"synthetic tenant rings parquet")
    rings_log = {
        "split": "test",
        "command": "run",
        "edge_subset": "tenant_135981_edges.parquet" if tenant_scope else None,
        "tenant_rule": ("explicit tenant_id=135981 for tenant-scoped edge subset"
                        if tenant_scope else "sender bank of earliest seed edge"),
        "aggregator": "full",
        "model": {"model_id": "gine_causal", "seed": 1, "aggregator": "full"},
        "out": str(rings_path),
    }
    rings_log.update(rings_updates or {})
    rings_log_path.write_text(json.dumps(rings_log), encoding="utf-8")
    if pooled:
        log = {"split": "test", "provenance": {"scope": "pooled"}}
    else:
        log = {
            "scope": "tenant", "tenant_id": 135981, "visibility": "tenant",
            "feature_scope": "tenant_view", "fx_rates_sha256": FX_HASH,
            "explainer_version": "0.4.0-narrative", "n_rings": 1,
            "n_explained": 1, "n_reproduces_shipped_ring": int(reproduced),
            "not_reproduced": [] if reproduced else [row["ring_id"]],
            "input_sha256": {"rings": {"path": str(rings_path),
                                         "sha256": hashlib.sha256(rings_path.read_bytes()).hexdigest()}},
        }
        log.update(log_updates or {})
    parquet_path = tmp_path / "explanations.parquet"
    pq.write_table(pa.Table.from_pylist([row]), parquet_path)
    log_path = Path(str(parquet_path) + ".log.json")
    log_path.write_text(json.dumps(log), encoding="utf-8")
    return parquet_path, log_path, rings_log_path


def test_read_handoff_converts_json_and_nonfinite_values(tmp_path):
    parquet_path, log_path, rings_log_path = _files(tmp_path)

    rows, log = read_handoff(parquet_path, log_path, rings_log_path)

    assert log["explainer_version"] == "0.4.0-narrative"
    assert rows[0]["evidence_summary"] == {"template": "FAN-OUT"}
    assert rows[0]["account_weights"][0]["hold_time_s"] is None
    assert rows[0]["provenance"]["loo"]["reproduces_shipped_ring"] is True
    assert rows[0]["fx_rates_sha256"] == FX_HASH
    assert rows[0]["provenance"]["feature_scope"] == "tenant_view"


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
        "currency_policy": "converted", "scope": "tenant", "tenant_id": 135981,
        "feature_scope": "tenant_view", "fx_rates_sha256": FX_HASH,
        "loo": {"reproduces_shipped_ring": False},
    })
    pq.write_table(pa.Table.from_pylist(table), parquet_path)

    with pytest.raises(ExplanationLoadError, match="does not confirm ring reproduction"):
        read_handoff(parquet_path, log_path, rings_log_path)


def test_read_handoff_rejects_global_ring_run(tmp_path):
    parquet_path, log_path, rings_log_path = _files(tmp_path, tenant_scope=False)

    with pytest.raises(ExplanationLoadError, match="tenant-scoped run"):
        read_handoff(parquet_path, log_path, rings_log_path)


@pytest.mark.parametrize("updates,match", [
    ({"log_updates": {"scope": None}}, "scope=tenant"),
    ({"log_updates": {"scope": "pooled"}}, "scope=tenant"),
    ({"log_updates": {"tenant_id": 999}}, "tenant mismatch between L4 log and source rings log"),
    ({"row_updates": {"tenant_id": 999}}, "tenant_id does not match L4 log tenant"),
    ({"row_updates": {"provenance": json.dumps({
        "aggregator_id": "full", "model_id": "gine_causal", "seed": 1,
        "rings_schema_version": 2, "explainer_version": "0.4.0-narrative",
        "currency_policy": "converted", "scope": "tenant", "tenant_id": 999,
        "feature_scope": "tenant_view", "fx_rates_sha256": FX_HASH,
        "loo": {"reproduces_shipped_ring": True},
    })}}, "row tenant_id does not match L4 log tenant"),
    ({"log_updates": {"input_sha256": {"rings": {"sha256": "0" * 64}}}}, "SHA-256 does not match"),
    ({"log_updates": {"fx_rates_sha256": "0" * 64}}, "L4 log fx_rates_sha256 does not match"),
    ({"row_updates": {"provenance": json.dumps({
        "aggregator_id": "full", "model_id": "gine_causal", "seed": 1,
        "rings_schema_version": 2, "explainer_version": "0.4.0-narrative",
        "currency_policy": "converted", "scope": "tenant", "tenant_id": 135981,
        "feature_scope": "pooled", "fx_rates_sha256": FX_HASH,
        "loo": {"reproduces_shipped_ring": True},
    })}}, "row feature_scope must be tenant_view"),
    ({"log_updates": {"feature_scope": "pooled_view"}}, "feature_scope must be tenant_view"),
    ({"row_updates": {"provenance": json.dumps({
        "aggregator_id": "full", "model_id": "gine_causal", "seed": 1,
        "rings_schema_version": 2, "explainer_version": "0.4.0-narrative",
        "currency_policy": "converted", "scope": "tenant", "tenant_id": 135981,
        "feature_scope": "tenant_view", "fx_rates_sha256": "0" * 64,
        "loo": {"reproduces_shipped_ring": True},
    })}}, "row fx_rates_sha256 does not match"),
    ({"reproduced": False}, "do not reproduce"),
])
def test_tenant_handoff_rejects_invalid_provenance_and_scope(tmp_path, updates, match):
    options = dict(updates)
    reproduced = options.pop("reproduced", True)
    parquet_path, log_path, rings_log_path = _files(tmp_path, reproduced=reproduced, **options)
    with pytest.raises(ExplanationLoadError, match=match):
        read_handoff(parquet_path, log_path, rings_log_path)


def test_tenant_handoff_rejects_tenant_mismatch_in_rings_log(tmp_path):
    parquet_path, log_path, rings_log_path = _files(
        tmp_path, rings_updates={"tenant_rule": "explicit tenant_id=999 for tenant-scoped edge subset"},
    )
    with pytest.raises(ExplanationLoadError, match="tenant mismatch between L4 log and source rings log"):
        read_handoff(parquet_path, log_path, rings_log_path)


def test_old_pooled_handoff_is_refused_for_tenant_loading(tmp_path):
    parquet_path, log_path, rings_log_path = _files(tmp_path, pooled=True)
    with pytest.raises(ExplanationLoadError, match="scope=tenant"):
        read_handoff(parquet_path, log_path, rings_log_path)
