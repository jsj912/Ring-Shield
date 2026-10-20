"""Load a synthetic tenant L4 handoff through the restricted loader role."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(0, str(PLATFORM_ROOT.parent))

from jobs.load_explanations import load_explanations
from contract.schema import RINGS_ORDER

TENANT_ID = 210
FX_HASH = "ee0e8a23b6037e4aeceb44b6874a70d7b46114559551fd2cf94a3842bb8d4ac6"


def test_synthetic_tenant_explanation_handoff_loads_and_persists_fx_hash(
        tmp_path, register_db_test_ids, repo_platform_config):
    suffix = uuid4().hex
    ring_id = f"full-gine_causal-1-l4-{suffix}"
    register_db_test_ids(ring_id)
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    test_started_at = datetime.now(timezone.utc)
    try:
        with admin.begin() as connection:
            connection.execute(text("""
                INSERT INTO rings
                  (tenant_id, ring_id, model_id, aggregator_id, seed, scope,
                   member_accounts, member_edges, seed_edges, expanded_edges,
                   confidence, topology_type, topology_probs, start_time, end_time,
                   status, payload)
                VALUES
                  (:tenant_id, :ring_id, 'gine_causal', 'full', 1, 'tenant',
                   ARRAY[21]::bigint[], ARRAY[17]::bigint[], ARRAY[17]::bigint[],
                   ARRAY[]::bigint[], 0.8, 'FAN-OUT', ARRAY[1.0]::float[],
                   10, 20, 'open', '{}'::jsonb)
            """), {"tenant_id": TENANT_ID, "ring_id": ring_id})

        rings_path = tmp_path / "rings-210.parquet"
        ring_row = {column: None for column in RINGS_ORDER}
        ring_row.update({"ring_id": ring_id, "tenant_id": TENANT_ID})
        pq.write_table(pa.Table.from_pylist([ring_row]), rings_path)
        rings_log_path = tmp_path / "rings-210.parquet.log.json"
        rings_log_path.write_text(json.dumps({
            "split": "test", "command": "run", "edge_subset": "edges-210.parquet",
            "tenant_rule": "explicit tenant_id=210 for tenant-scoped edge subset",
            "model": {"model_id": "gine_causal", "seed": 1, "aggregator": "full"},
            "out": rings_path.name,
        }), encoding="utf-8")

        provenance = {
            "aggregator_id": "full", "model_id": "gine_causal", "seed": 1,
            "explainer_version": "0.4.0-narrative", "rings_schema_version": 1,
            "currency_policy": "converted", "scope": "tenant", "tenant_id": TENANT_ID,
            "feature_scope": "tenant_view", "fx_rates_sha256": FX_HASH,
            "loo": {"reproduces_shipped_ring": True},
        }
        explanation_path = tmp_path / "explanations-210.parquet"
        pq.write_table(pa.Table.from_pylist([{
            "ring_id": ring_id, "tenant_id": TENANT_ID,
            "edge_weights": [{"edge_id": 17, "weight": 0.8}],
            "account_weights": [{"account_id": 21, "weight": 1.0}],
            "feature_weights": [{"feature_name": "amount", "weight": 0.5,
                                 "top_edge_id": 17}],
            "topology_type": "FAN-OUT", "topology_prob": 0.9,
            "narrative": "synthetic tenant explanation",
            "evidence_summary": {"template": "FAN-OUT"}, "latency_ms": 4,
            "provenance": json.dumps(provenance),
        }]), explanation_path)
        explanation_log = {
            "scope": "tenant", "tenant_id": TENANT_ID, "visibility": "visible",
            "feature_scope": "tenant_view", "fx_rates_sha256": FX_HASH,
            "explainer_version": "0.4.0-narrative", "n_rings": 1,
            "n_explained": 1, "n_reproduces_shipped_ring": 1,
            "not_reproduced": [],
            "input_sha256": {"rings": {
                "path": str(rings_path),
                "sha256": hashlib.sha256(rings_path.read_bytes()).hexdigest(),
            }},
        }
        explanation_log_path = Path(str(explanation_path) + ".log.json")
        explanation_log_path.write_text(json.dumps(explanation_log), encoding="utf-8")

        result = load_explanations(explanation_path, explanation_log_path, rings_log_path)
        assert result == {"explanations_loaded": 1, "rows_validated": 1}
        with admin.connect() as connection:
            stored = connection.execute(text("""
                SELECT provenance->>'feature_scope', provenance->>'fx_rates_sha256',
                       fx_rates_sha256
                FROM explanations
                WHERE tenant_id = :tenant_id AND ring_id = :ring_id
                  AND explainer_version = '0.4.0-narrative'
            """), {"tenant_id": TENANT_ID, "ring_id": ring_id}).one()
        assert tuple(stored) == ("tenant_view", FX_HASH, FX_HASH)
    finally:
        with admin.begin() as connection:
            connection.execute(text("""
                DELETE FROM explanations
                WHERE tenant_id = :tenant_id AND ring_id = :ring_id
            """), {"tenant_id": TENANT_ID, "ring_id": ring_id})
            connection.execute(text("""
                DELETE FROM audit_log
                WHERE tenant_id = :tenant_id AND action = 'explanations.load_completed'
                  AND at >= :started_at
            """), {"tenant_id": TENANT_ID, "started_at": test_started_at})
            connection.execute(text(
                "DELETE FROM rings WHERE tenant_id = :tenant_id AND ring_id = :ring_id"
            ), {"tenant_id": TENANT_ID, "ring_id": ring_id})
        admin.dispose()
