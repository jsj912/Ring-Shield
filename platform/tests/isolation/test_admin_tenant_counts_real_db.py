"""Exercise registry counts through the admin API against PostgreSQL."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal, create_access_token  # noqa: E402
from api.main import app  # noqa: E402


def test_admin_tenant_registry_reports_ring_and_verdict_counts(register_db_test_ids):
    run_marker = uuid4().hex
    tenant_id = 800_000_000_000 + uuid4().int % 100_000_000
    bank_code = 900_000_000 + uuid4().int % 90_000_000
    ring_id = f"admin-count-{run_marker}"
    email = f"admin-count-{run_marker}@test.invalid"
    register_db_test_ids(ring_id)
    engine = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    verdict_id = None
    try:
        with engine.begin() as connection:
            admin_row = connection.execute(text(
                "SELECT user_id, email FROM users WHERE role = 'admin' AND tenant_id IS NULL "
                "ORDER BY user_id LIMIT 1"
            )).one()
            connection.execute(text("""
                INSERT INTO tenants (tenant_id, bank_code, name, is_loaded)
                VALUES (:tenant_id, :bank_code, :name, true)
            """), {"tenant_id": tenant_id, "bank_code": bank_code,
                  "name": f"Admin count {run_marker}"})
            user_id = connection.execute(text("""
                INSERT INTO users (tenant_id, email, password_hash, role)
                VALUES (:tenant_id, :email, 'fixture-only-hash', 'analyst')
                RETURNING user_id
            """), {"tenant_id": tenant_id, "email": email}).scalar_one()
            connection.execute(text("""
                INSERT INTO rings
                  (tenant_id, ring_id, model_id, aggregator_id, seed, scope,
                   member_accounts, member_edges, seed_edges, expanded_edges,
                   confidence, topology_type, topology_probs, start_time, end_time)
                VALUES
                  (:tenant_id, :ring_id, 'fixture-model', 'fixture-aggregator', 1, 'tenant',
                   ARRAY[1, 2]::bigint[], ARRAY[]::bigint[], ARRAY[]::bigint[],
                   ARRAY[]::bigint[], 0.9, 'CYCLE', ARRAY[1.0]::float[], 1, 2)
            """), {"tenant_id": tenant_id, "ring_id": ring_id})
            verdict_id = connection.execute(text("""
                INSERT INTO verdicts
                  (tenant_id, ring_id, user_id, verdict, corrected_members,
                   corrected_edges, is_simulated)
                VALUES (:tenant_id, :ring_id, :user_id, 'confirm',
                        ARRAY[]::bigint[], ARRAY[]::bigint[], false)
                RETURNING verdict_id
            """), {"tenant_id": tenant_id, "ring_id": ring_id,
                  "user_id": user_id}).scalar_one()
        register_db_test_ids(str(verdict_id))

        token, _ = create_access_token(Principal(
            user_id=admin_row.user_id, tenant_id=None, role="admin", email=admin_row.email,
        ))
        response = TestClient(app).get(
            "/admin/tenants", headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        tenant = next(row for row in response.json() if row["tenant_id"] == tenant_id)
        assert tenant["ring_count"] == 1
        assert tenant["verdict_count"] == 1
        assert "email" not in tenant
        assert "password" not in str(tenant).lower()
    finally:
        with engine.begin() as connection:
            connection.execute(text(
                "DELETE FROM audit_log WHERE tenant_id = :tenant_id OR object_id = :ring_id"
            ), {"tenant_id": tenant_id, "ring_id": ring_id})
            connection.execute(text(
                "DELETE FROM verdicts WHERE tenant_id = :tenant_id AND ring_id = :ring_id"
            ), {"tenant_id": tenant_id, "ring_id": ring_id})
            connection.execute(text(
                "DELETE FROM rings WHERE tenant_id = :tenant_id AND ring_id = :ring_id"
            ), {"tenant_id": tenant_id, "ring_id": ring_id})
            connection.execute(text(
                "DELETE FROM users WHERE tenant_id = :tenant_id AND email = :email"
            ), {"tenant_id": tenant_id, "email": email})
            connection.execute(text("DELETE FROM tenants WHERE tenant_id = :tenant_id"),
                               {"tenant_id": tenant_id})
        engine.dispose()
