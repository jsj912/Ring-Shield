"""Integration coverage for identical ring IDs stored for separate tenants."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal, create_access_token
from api.main import app
from jobs.load_contract import load_rings


def _token(email: str, tenant_id: int) -> str:
    engine = create_engine(os.environ["RINGSHIELD_AUTH_DATABASE_URL"])
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT set_config('app.user_role', 'auth', true)"))
            user_id = connection.execute(text("SELECT user_id FROM users WHERE email=:email"),
                                         {"email": email}).scalar_one()
    finally:
        engine.dispose()
    token, _ = create_access_token(Principal(
        user_id=user_id, tenant_id=tenant_id, role="analyst", email=email,
    ))
    return token


def test_identical_ring_ids_load_and_api_reads_stay_tenant_scoped(
        tmp_path, register_db_test_ids):
    fixture_dir = Path(os.environ["RINGSHIELD_TEST_FIXTURE_DIR"])
    source = pq.read_table(fixture_dir / "rings.parquet")
    common_ring_id = f"shared-demo-model-7-{uuid4().hex[:8]}"
    register_db_test_ids(common_ring_id)
    test_started_at = datetime.now(timezone.utc)
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    try:
        for tenant_id, confidence in ((210, 0.71), (220, 0.82)):
            row = next(row for row in source.to_pylist() if row["tenant_id"] == tenant_id)
            row["ring_id"] = common_ring_id
            row["confidence"] = confidence
            ring_path = tmp_path / f"tenant-{tenant_id}-rings.parquet"
            pq.write_table(pa.Table.from_pylist([row], schema=source.schema), ring_path)
            Path(str(ring_path) + ".log.json").write_text(
                json.dumps({"split": "test"}), encoding="utf-8",
            )
            assert load_rings(ring_path, scope="tenant")["rings_loaded"] == 1

        with admin.connect() as connection:
            rows = connection.execute(text("""
                SELECT tenant_id, confidence FROM rings
                WHERE ring_id = :ring_id ORDER BY tenant_id
            """), {"ring_id": common_ring_id}).all()
        assert [(row.tenant_id, row.confidence) for row in rows] == [(210, 0.71), (220, 0.82)]

        with admin.begin() as connection:
            for tenant_id in (210, 220):
                provenance = {
                    "aggregator_id": "full", "model_id": "demo-model", "seed": 7,
                    "feature_scope": "tenant_view", "fx_rates_sha256": "a" * 64,
                }
                connection.execute(text("""
                    INSERT INTO explanations
                      (tenant_id, ring_id, explainer_version, edge_weights,
                       account_weights, feature_weights, narrative, evidence_summary,
                       latency_ms, provenance, fx_rates_sha256)
                    VALUES (:tenant_id, :ring_id, 'collision-test', '[]'::jsonb,
                            '[]'::jsonb, '[]'::jsonb, :narrative, '{}'::jsonb,
                            1, CAST(:provenance AS jsonb), :fx_hash)
                """), {
                    "tenant_id": tenant_id, "ring_id": common_ring_id,
                    "narrative": f"tenant-{tenant_id}-explanation",
                    "provenance": json.dumps(provenance), "fx_hash": "a" * 64,
                })
                user_id = connection.execute(text("""
                    SELECT user_id FROM users
                    WHERE tenant_id = :tenant_id AND email = :email
                """), {"tenant_id": tenant_id,
                      "email": f"analyst-{tenant_id}@test.invalid"}).scalar_one()
                connection.execute(text("""
                    INSERT INTO verdicts
                      (tenant_id, ring_id, user_id, verdict, corrected_members,
                       corrected_edges, is_simulated)
                    VALUES (:tenant_id, :ring_id, :user_id, :verdict,
                            ARRAY[]::bigint[], ARRAY[]::bigint[], false)
                """), {"tenant_id": tenant_id, "ring_id": common_ring_id,
                      "user_id": user_id,
                      "verdict": "confirm" if tenant_id == 210 else "reject"})

        client = TestClient(app)
        for tenant_id, confidence in ((210, 0.71), (220, 0.82)):
            token = _token(f"analyst-{tenant_id}@test.invalid", tenant_id)
            headers = {"Authorization": f"Bearer {token}"}
            response = client.get(
                f"/tenants/{tenant_id}/rings/{common_ring_id}",
                headers=headers,
            )
            assert response.status_code == 200
            assert response.json()["tenant_id"] == tenant_id
            assert response.json()["confidence"] == confidence
            searched = client.get(
                f"/tenants/{tenant_id}/rings", headers=headers,
                params={"status": "open", "q": common_ring_id},
            )
            assert searched.status_code == 200
            assert [(item["tenant_id"], item["ring_id"])
                    for item in searched.json()["items"]] == [(tenant_id, common_ring_id)]
            explanation = client.get(
                f"/tenants/{tenant_id}/rings/{common_ring_id}/explanation",
                headers=headers,
            )
            assert explanation.status_code == 200
            assert explanation.json()["narrative"] == f"tenant-{tenant_id}-explanation"
            assert explanation.json()["provenance"]["feature_scope"] == "tenant_view"
            assert explanation.json()["provenance"]["fx_rates_sha256"] == "a" * 64
            verdicts = client.get(
                f"/tenants/{tenant_id}/rings/{common_ring_id}/verdicts",
                headers=headers,
            )
            assert verdicts.status_code == 200
            assert [item["verdict"] for item in verdicts.json()["items"]] == [
                "confirm" if tenant_id == 210 else "reject"
            ]
    finally:
        with admin.begin() as connection:
            connection.execute(text("""
                DELETE FROM verdicts WHERE tenant_id IN (210, 220) AND ring_id = :ring_id
            """), {"ring_id": common_ring_id})
            connection.execute(text("""
                DELETE FROM explanations WHERE tenant_id IN (210, 220) AND ring_id = :ring_id
            """), {"ring_id": common_ring_id})
            connection.execute(text("""
                DELETE FROM audit_log
                WHERE tenant_id IN (210, 220) AND at >= :started_at
                  AND (object_id = :ring_id OR action = 'rings.load_completed')
            """), {"started_at": test_started_at, "ring_id": common_ring_id})
            connection.execute(text("""
                DELETE FROM rings WHERE tenant_id IN (210, 220) AND ring_id = :ring_id
            """), {"ring_id": common_ring_id})
        admin.dispose()


def test_ring_upsert_counts_writes_and_preserves_closed_ring(tmp_path, register_db_test_ids):
    fixture_dir = Path(os.environ["RINGSHIELD_TEST_FIXTURE_DIR"])
    source = pq.read_table(fixture_dir / "rings.parquet")
    row = next(item for item in source.to_pylist() if item["tenant_id"] == 210)
    ring_id = f"demo-model-7-upsert-{uuid4().hex[:8]}"
    register_db_test_ids(ring_id)
    test_started_at = datetime.now(timezone.utc)
    row["ring_id"] = ring_id
    ring_path = tmp_path / "tenant-210-ring-upsert.parquet"
    Path(str(ring_path) + ".log.json").write_text(json.dumps({"split": "test"}), encoding="utf-8")

    def write_ring(confidence: float) -> None:
        row["confidence"] = confidence
        pq.write_table(pa.Table.from_pylist([row], schema=source.schema), ring_path)

    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    try:
        write_ring(0.61)
        first = load_rings(ring_path, scope="tenant")
        assert first["rings_loaded"] == 1
        assert first.get("rings_preserved_after_verdict", 0) == 0

        write_ring(0.72)
        second = load_rings(ring_path, scope="tenant")
        assert second["rings_loaded"] == 1
        with admin.begin() as connection:
            open_confidence = connection.execute(text("""
                SELECT confidence FROM rings WHERE tenant_id = 210 AND ring_id = :ring_id
            """), {"ring_id": ring_id}).scalar_one()
            connection.execute(text("""
                UPDATE rings SET status = 'confirmed'
                WHERE tenant_id = 210 AND ring_id = :ring_id
            """), {"ring_id": ring_id})
        assert open_confidence == 0.72

        write_ring(0.99)
        third = load_rings(ring_path, scope="tenant")
        assert third.get("rings_loaded", 0) == 0
        assert third["rings_preserved_after_verdict"] == 1
        with admin.connect() as connection:
            stored_confidence = connection.execute(text("""
                SELECT confidence FROM rings WHERE tenant_id = 210 AND ring_id = :ring_id
            """), {"ring_id": ring_id}).scalar_one()
        assert stored_confidence == 0.72
    finally:
        with admin.begin() as connection:
            connection.execute(text("""
                DELETE FROM audit_log
                WHERE tenant_id = 210 AND action = 'rings.load_completed' AND at >= :started_at
            """), {"started_at": test_started_at})
            connection.execute(text("DELETE FROM rings WHERE tenant_id = 210 AND ring_id = :ring_id"),
                               {"ring_id": ring_id})
        admin.dispose()
