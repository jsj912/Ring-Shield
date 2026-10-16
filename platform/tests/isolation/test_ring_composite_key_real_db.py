"""Integration coverage for identical ring IDs stored for separate tenants."""

from __future__ import annotations

import json
import os
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


def test_identical_ring_ids_load_and_api_reads_stay_tenant_scoped(tmp_path):
    fixture_dir = Path(os.environ["RINGSHIELD_TEST_FIXTURE_DIR"])
    source = pq.read_table(fixture_dir / "rings.parquet")
    common_ring_id = f"shared-demo-model-7-{uuid4().hex[:8]}"
    for tenant_id, confidence in ((210, 0.71), (220, 0.82)):
        row = next(row for row in source.to_pylist() if row["tenant_id"] == tenant_id)
        row["ring_id"] = common_ring_id
        row["confidence"] = confidence
        ring_path = tmp_path / f"tenant-{tenant_id}-rings.parquet"
        pq.write_table(pa.Table.from_pylist([row], schema=source.schema), ring_path)
        Path(str(ring_path) + ".log.json").write_text(json.dumps({"split": "test"}), encoding="utf-8")
        assert load_rings(ring_path, scope="tenant")["rings_loaded"] == 1

    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    try:
        with admin.connect() as connection:
            rows = connection.execute(text("""
                SELECT tenant_id, confidence FROM rings
                WHERE ring_id = :ring_id ORDER BY tenant_id
            """), {"ring_id": common_ring_id}).all()
    finally:
        admin.dispose()
    assert [(row.tenant_id, row.confidence) for row in rows] == [(210, 0.71), (220, 0.82)]

    client = TestClient(app)
    for tenant_id, confidence in ((210, 0.71), (220, 0.82)):
        token = _token(f"analyst-{tenant_id}@test.invalid", tenant_id)
        response = client.get(
            f"/tenants/{tenant_id}/rings/{common_ring_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["tenant_id"] == tenant_id
        assert response.json()["confidence"] == confidence
