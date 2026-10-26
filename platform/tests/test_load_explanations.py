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
sys.path.insert(0, str(PLATFORM_ROOT.parent))

from jobs.check_explanations import main as check_explanations_main
from jobs.load_explanations import ExplanationLoadError, read_handoff
from contract.schema import RINGS_ORDER, RINGS_ORDER_V1

pytestmark = pytest.mark.usefixtures("repo_platform_config")

FX_HASH = "ee0e8a23b6037e4aeceb44b6874a70d7b46114559551fd2cf94a3842bb8d4ac6"


def _files(tmp_path, *, reproduced=True, tenant_scope=True, log_updates=None,
           row_updates=None, rings_updates=None, pooled=False, ring_columns=None):
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
    source_columns = RINGS_ORDER if ring_columns is None else ring_columns
    pq.write_table(pa.Table.from_pylist([{column: None for column in source_columns}]), rings_path)
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


def _set_row_schema_version(parquet_path, row_index, version):
    rows = pq.read_table(parquet_path).to_pylist()
    provenance = json.loads(rows[row_index]["provenance"])
    provenance["rings_schema_version"] = version
    rows[row_index]["provenance"] = json.dumps(provenance)
    pq.write_table(pa.Table.from_pylist(rows), parquet_path)


def test_read_handoff_converts_json_and_nonfinite_values(tmp_path):
    parquet_path, log_path, rings_log_path = _files(tmp_path)

    rows, log = read_handoff(parquet_path, log_path, rings_log_path)

    assert log["explainer_version"] == "0.4.0-narrative"
    assert rows[0]["evidence_summary"] == {"template": "FAN-OUT"}
    assert rows[0]["account_weights"][0]["hold_time_s"] is None
    assert rows[0]["provenance"]["loo"]["reproduces_shipped_ring"] is True
    assert rows[0]["fx_rates_sha256"] == FX_HASH
    assert rows[0]["provenance"]["feature_scope"] == "tenant_view"
    assert rows[0]["provenance"]["rings_schema_version"] == 2


def test_read_only_explanation_check_reports_row_count(tmp_path, capsys):
    parquet_path, log_path, rings_log_path = _files(tmp_path)

    assert check_explanations_main([
        "--explanations", str(parquet_path),
        "--run-log", str(log_path),
        "--rings-log", str(rings_log_path),
    ]) == 0
    assert capsys.readouterr().out.startswith("OK 1 rows:")


def test_read_only_explanation_check_reports_refusal_without_stopping_other_files(tmp_path, capsys):
    good_dir = tmp_path / "good"
    good_dir.mkdir()
    good = _files(good_dir)
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    bad = _files(bad_dir, log_updates={"scope": "pooled"})

    assert check_explanations_main([
        "--explanations", str(good[0]), "--explanations", str(bad[0]),
        "--run-log", str(good[1]), "--run-log", str(bad[1]),
        "--rings-log", str(good[2]), "--rings-log", str(bad[2]),
    ]) == 1
    output = capsys.readouterr().out
    assert "OK 1 rows:" in output
    assert "REFUSED" in output and "scope=tenant" in output


def test_unknown_topology_accepts_nan_probability_and_uses_ring_metadata(tmp_path):
    parquet_path, log_path, rings_log_path = _files(
        tmp_path, row_updates={"topology_type": "UNKNOWN", "topology_prob": float("nan")},
    )

    rows, _ = read_handoff(parquet_path, log_path, rings_log_path)

    assert rows[0]["_source_topology_type"] is None


def test_unknown_topology_accepts_null_probability(tmp_path):
    parquet_path, log_path, rings_log_path = _files(
        tmp_path, row_updates={"topology_type": "UNKNOWN", "topology_prob": None},
    )

    rows, _ = read_handoff(parquet_path, log_path, rings_log_path)

    assert rows[0]["_source_topology_type"] is None


def test_known_topology_rejects_nan_probability(tmp_path):
    parquet_path, log_path, rings_log_path = _files(
        tmp_path, row_updates={"topology_type": "FAN-OUT", "topology_prob": float("nan")},
    )

    with pytest.raises(ExplanationLoadError, match="may be NaN only when topology_type is UNKNOWN"):
        read_handoff(parquet_path, log_path, rings_log_path)


@pytest.mark.parametrize("probability", [float("inf"), float("-inf")])
def test_topology_rejects_infinity(tmp_path, probability):
    parquet_path, log_path, rings_log_path = _files(
        tmp_path, row_updates={"topology_type": "UNKNOWN", "topology_prob": probability},
    )

    with pytest.raises(ExplanationLoadError, match="topology_prob must not be infinite"):
        read_handoff(parquet_path, log_path, rings_log_path)


@pytest.mark.parametrize("probability", [-0.01, 1.01])
def test_known_topology_rejects_probability_outside_unit_interval(tmp_path, probability):
    parquet_path, log_path, rings_log_path = _files(
        tmp_path, row_updates={"topology_type": "FAN-OUT", "topology_prob": probability},
    )

    with pytest.raises(ExplanationLoadError, match="topology_prob must be finite and between 0 and 1"):
        read_handoff(parquet_path, log_path, rings_log_path)


def test_version_1_explanation_is_refused_for_version_2_rings(tmp_path):
    parquet_path, log_path, rings_log_path = _files(tmp_path)
    _set_row_schema_version(parquet_path, 0, 1)

    with pytest.raises(ExplanationLoadError, match=r"row declares rings schema version 1.*rings are version 2"):
        read_handoff(parquet_path, log_path, rings_log_path)


def test_mixed_explanation_row_schema_versions_are_refused(tmp_path):
    parquet_path, log_path, rings_log_path = _files(tmp_path)
    rows = pq.read_table(parquet_path).to_pylist()
    second = dict(rows[0])
    second["ring_id"] = "full-gine_causal-1-1"
    rows.append(second)
    pq.write_table(pa.Table.from_pylist(rows), parquet_path)
    _set_row_schema_version(parquet_path, 1, 1)
    log = json.loads(log_path.read_text(encoding="utf-8"))
    log.update({"n_rings": 2, "n_explained": 2, "n_reproduces_shipped_ring": 2})
    log_path.write_text(json.dumps(log), encoding="utf-8")

    with pytest.raises(ExplanationLoadError, match=r"row declares rings schema version 1.*rings are version 2"):
        read_handoff(parquet_path, log_path, rings_log_path)


def test_version_1_rings_are_refused_when_version_2_is_configured(tmp_path):
    parquet_path, log_path, rings_log_path = _files(tmp_path, ring_columns=RINGS_ORDER_V1)

    with pytest.raises(ExplanationLoadError, match=r"source tenant rings schema version 1.*configured l4.rings_schema_version 2"):
        read_handoff(parquet_path, log_path, rings_log_path)


def test_source_rings_version_must_match_configured_version(tmp_path, monkeypatch):
    import yaml

    from settings import load_platform_config

    config = yaml.safe_load((PLATFORM_ROOT / "config.yaml").read_text(encoding="utf-8"))
    config["l4"]["rings_schema_version"] = 1
    config_path = tmp_path / "platform-config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv("RINGSHIELD_PLATFORM_CONFIG", str(config_path))
    load_platform_config.cache_clear()
    parquet_path, log_path, rings_log_path = _files(tmp_path)

    with pytest.raises(ExplanationLoadError, match=r"source tenant rings schema version 2.*configured l4.rings_schema_version 1"):
        read_handoff(parquet_path, log_path, rings_log_path)


def test_wrong_rings_column_set_is_refused(tmp_path):
    wrong_columns = list(RINGS_ORDER)
    wrong_columns[-1] = "unexpected_role_column"
    parquet_path, log_path, rings_log_path = _files(tmp_path, ring_columns=wrong_columns)

    with pytest.raises(ExplanationLoadError, match="columns do not match schema version"):
        read_handoff(parquet_path, log_path, rings_log_path)


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


def test_identity_provenance_must_match_across_all_rows(tmp_path):
    parquet_path, log_path, rings_log_path = _files(tmp_path)
    rows = pq.read_table(parquet_path).to_pylist()
    second = dict(rows[0])
    second["ring_id"] = "full-gine_causal-1-1"
    second_provenance = json.loads(second["provenance"])
    second_provenance["seed"] = 2
    second["provenance"] = json.dumps(second_provenance)
    pq.write_table(pa.Table.from_pylist([rows[0], second]), parquet_path)
    log = json.loads(log_path.read_text(encoding="utf-8"))
    log.update({"n_rings": 2, "n_explained": 2, "n_reproduces_shipped_ring": 2})
    log_path.write_text(json.dumps(log), encoding="utf-8")

    with pytest.raises(ExplanationLoadError, match="row provenance differs across explanation rows"):
        read_handoff(parquet_path, log_path, rings_log_path)
