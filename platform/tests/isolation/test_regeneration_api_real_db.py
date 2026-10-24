"""PostgreSQL acceptance for atomic partial-verdict regeneration creation."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal, create_access_token  # noqa: E402
from api.main import app  # noqa: E402
from api.routers import verdicts as verdict_routes  # noqa: E402
from db.session import get_engine, simulator_db_session  # noqa: E402
from services.verdicts import record_verdict  # noqa: E402


TENANT = 210


def _token(tenant_id: int = TENANT) -> str:
    engine = create_engine(os.environ["RINGSHIELD_AUTH_DATABASE_URL"])
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT set_config('app.user_role', 'auth', true)"))
            user_id, email = connection.execute(text("""
                SELECT user_id, email FROM users WHERE tenant_id = :tenant_id
                ORDER BY user_id LIMIT 1
            """), {"tenant_id": tenant_id}).one()
    finally:
        engine.dispose()
    token, _ = create_access_token(Principal(
        user_id=user_id, tenant_id=tenant_id, role="analyst", email=email,
    ))
    return token


def _seed_ring(connection, ring_id: str, edge_base: int) -> tuple[int, int]:
    edge_one, edge_two = edge_base, edge_base + 1
    connection.execute(text("""
        INSERT INTO rings
          (tenant_id, ring_id, model_id, aggregator_id, seed, scope,
           member_accounts, member_edges, seed_edges, expanded_edges,
           confidence, topology_type, topology_probs, start_time, end_time,
           status, payload)
        VALUES (:tenant_id, :ring_id, 'gine_causal', 'full', 1, 'tenant',
                ARRAY[11,12,13]::bigint[], ARRAY[:edge_one,:edge_two]::bigint[],
                ARRAY[:edge_one]::bigint[], ARRAY[:edge_two]::bigint[], 0.8,
                'CYCLE', ARRAY[1.0]::float[], 10, 20, 'open', '{}'::jsonb)
    """), {"tenant_id": TENANT, "ring_id": ring_id,
          "edge_one": edge_one, "edge_two": edge_two})
    for edge_id, from_id, to_id in ((edge_one, 11, 12), (edge_two, 12, 13)):
        connection.execute(text("""
            INSERT INTO transactions
              (tenant_id, edge_id, from_id, to_id, from_bank, to_bank, timestamp)
            VALUES (:tenant_id, :edge_id, :from_id, :to_id, :from_bank, :to_bank, 100)
        """), {"tenant_id": TENANT, "edge_id": edge_id, "from_id": from_id,
              "to_id": to_id, "from_bank": TENANT, "to_bank": TENANT})
    return edge_one, edge_two


def _cleanup(admin, *, ring_id: str, edge_base: int, register_db_test_ids) -> None:
    with admin.begin() as connection:
        job_ids = [row[0] for row in connection.execute(text("""
            SELECT job_id FROM explanation_jobs
            WHERE tenant_id=:tenant AND ring_id=:ring
        """), {"tenant": TENANT, "ring": ring_id}).all()]
        verdict_ids = [row[0] for row in connection.execute(text("""
            SELECT verdict_id FROM verdicts
            WHERE tenant_id=:tenant AND ring_id=:ring
        """), {"tenant": TENANT, "ring": ring_id}).all()]
        register_db_test_ids(*job_ids, *(str(value) for value in verdict_ids))
        connection.execute(text("DELETE FROM explanation_jobs WHERE tenant_id=:tenant AND ring_id=:ring"),
                           {"tenant": TENANT, "ring": ring_id})
        connection.execute(text("DELETE FROM explanations WHERE tenant_id=:tenant AND ring_id=:ring"),
                           {"tenant": TENANT, "ring": ring_id})
        object_ids = [*job_ids, *(str(value) for value in verdict_ids)]
        if object_ids:
            connection.execute(text("""
                DELETE FROM audit_log WHERE tenant_id=:tenant
                  AND object_id = ANY(CAST(:object_ids AS text[]))
                  AND object_type IN ('explanation_job', 'verdict')
            """), {"tenant": TENANT, "object_ids": object_ids})
        connection.execute(text("DELETE FROM verdicts WHERE tenant_id=:tenant AND ring_id=:ring"),
                           {"tenant": TENANT, "ring": ring_id})
        connection.execute(text("DELETE FROM rings WHERE tenant_id=:tenant AND ring_id=:ring"),
                           {"tenant": TENANT, "ring": ring_id})
        connection.execute(text("DELETE FROM transactions WHERE tenant_id=:tenant AND edge_id IN (:one,:two)"),
                           {"tenant": TENANT, "one": edge_base, "two": edge_base + 1})


def test_partial_verdict_job_and_audit_commit_atomically(monkeypatch, register_db_test_ids):
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    suffix = uuid4().hex
    ring_id = f"partial-api-{suffix}"
    edge_base = 700_000_000 + int(suffix[:6], 16) * 2
    register_db_test_ids(ring_id)
    test_started_at = datetime.now(timezone.utc)
    job_id = None
    verdict_id = None
    launches = []
    monkeypatch.setattr(verdict_routes, "load_platform_config", lambda: {
        "l4": {"regenerate_url": "https://l4.example.test/regenerate"},
    })
    monkeypatch.setattr(verdict_routes, "launch_regeneration_process", launches.append)
    try:
        with admin.begin() as connection:
            _seed_ring(connection, ring_id, edge_base)
        response = TestClient(app).post(
            f"/tenants/{TENANT}/rings/{ring_id}/verdicts",
            headers={"Authorization": f"Bearer {_token()}"},
            json={"verdict": "partial", "corrected_members": [11, 12],
                  "note": "Keep the validated core"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        verdict_id = body["verdict_id"]
        job_id = body["regeneration"]["job_id"]
        register_db_test_ids(str(verdict_id), job_id)
        assert body["regeneration"]["status"] == "queued"
        assert launches == [job_id]
        with admin.connect() as connection:
            stored = connection.execute(text("""
                SELECT v.verdict, v.corrected_members, v.corrected_edges, r.status
                FROM verdicts AS v JOIN rings AS r
                  ON r.tenant_id = v.tenant_id AND r.ring_id = v.ring_id
                WHERE v.tenant_id=:tenant AND v.verdict_id=:verdict_id
            """), {"tenant": TENANT, "verdict_id": verdict_id}).one()
            job = connection.execute(text("""
                SELECT status, excluded_members, excluded_edges, requested_by
                FROM explanation_jobs WHERE tenant_id=:tenant AND job_id=:job_id
            """), {"tenant": TENANT, "job_id": job_id}).one()
            actions = connection.execute(text("""
                SELECT action, object_id FROM audit_log
                WHERE tenant_id=:tenant AND at >= :started_at
                  AND object_id IN (:job_id, :verdict_id)
                ORDER BY action
            """), {"tenant": TENANT, "started_at": test_started_at,
                  "job_id": job_id, "verdict_id": str(verdict_id)}).all()
        assert stored == ("partial", [11, 12], [], "partial")
        assert job[0:3] == ("queued", [13], [])
        assert len(actions) == 2
        assert {row.action for row in actions} == {
            "verdict.recorded", "explanation.regeneration_requested",
        }
    finally:
        try:
            _cleanup(admin, ring_id=ring_id, edge_base=edge_base,
                     register_db_test_ids=register_db_test_ids)
        finally:
            admin.dispose()


def test_job_insert_failure_rolls_back_partial_verdict(monkeypatch, register_db_test_ids):
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    suffix = uuid4().hex
    ring_id = f"partial-rollback-{suffix}"
    edge_base = 710_000_000 + int(suffix[:6], 16) * 2
    register_db_test_ids(ring_id)
    test_started_at = datetime.now(timezone.utc)
    monkeypatch.setattr(verdict_routes, "load_platform_config", lambda: {
        "l4": {"regenerate_url": "https://l4.example.test/regenerate"},
    })
    engine = get_engine()

    def fail_job_insert(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith("insert into explanation_jobs"):
            raise OSError("forced job insert failure")

    try:
        with admin.begin() as connection:
            _seed_ring(connection, ring_id, edge_base)
        event.listen(engine, "before_cursor_execute", fail_job_insert)
        response = TestClient(app, raise_server_exceptions=False).post(
            f"/tenants/{TENANT}/rings/{ring_id}/verdicts",
            headers={"Authorization": f"Bearer {_token()}"},
            json={"verdict": "partial", "corrected_members": [11, 12], "note": "Keep core"},
        )
        assert response.status_code == 500
        event.remove(engine, "before_cursor_execute", fail_job_insert)
        with admin.connect() as connection:
            verdict_count = connection.execute(text(
                "SELECT count(*) FROM verdicts WHERE tenant_id=:tenant AND ring_id=:ring"
            ), {"tenant": TENANT, "ring": ring_id}).scalar_one()
            ring_status = connection.execute(text(
                "SELECT status FROM rings WHERE tenant_id=:tenant AND ring_id=:ring"
            ), {"tenant": TENANT, "ring": ring_id}).scalar_one()
            job_count = connection.execute(text(
                "SELECT count(*) FROM explanation_jobs WHERE tenant_id=:tenant AND ring_id=:ring"
            ), {"tenant": TENANT, "ring": ring_id}).scalar_one()
            audit_count = connection.execute(text("""
                SELECT count(*) FROM audit_log WHERE tenant_id=:tenant AND at >= :started_at
                  AND action IN ('verdict.recorded', 'explanation.regeneration_requested')
                  AND object_type IN ('verdict', 'explanation_job')
            """), {"tenant": TENANT, "started_at": test_started_at}).scalar_one()
        assert (verdict_count, ring_status, job_count, audit_count) == (0, "open", 0, 0)
    finally:
        if event.contains(engine, "before_cursor_execute", fail_job_insert):
            event.remove(engine, "before_cursor_execute", fail_job_insert)
        try:
            _cleanup(admin, ring_id=ring_id, edge_base=edge_base,
                     register_db_test_ids=register_db_test_ids)
        finally:
            admin.dispose()


def test_simulated_partial_verdict_never_creates_regeneration_job(register_db_test_ids):
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    suffix = uuid4().hex
    ring_id = f"simulated-partial-{suffix}"
    edge_base = 720_000_000 + int(suffix[:6], 16) * 2
    register_db_test_ids(ring_id)
    verdict_id = None
    try:
        with admin.begin() as connection:
            _seed_ring(connection, ring_id, edge_base)
            user_id = connection.execute(text(
                "SELECT user_id FROM users WHERE tenant_id=:tenant ORDER BY user_id LIMIT 1"
            ), {"tenant": TENANT}).scalar_one()
        with simulator_db_session(tenant_id=TENANT) as session:
            from db.models import Ring

            ring = session.get(Ring, {"tenant_id": TENANT, "ring_id": ring_id})
            row = record_verdict(
                session, ring=ring, tenant_id=TENANT, ring_id=ring_id,
                user_id=user_id, verdict="partial", corrected_members=[11, 12],
                note="simulated partial verdict", is_simulated=True, actor="simulator",
            )
            verdict_id = row.verdict_id
        register_db_test_ids(str(verdict_id))
        with admin.connect() as connection:
            stored = connection.execute(text("""
                SELECT is_simulated FROM verdicts
                WHERE tenant_id=:tenant AND verdict_id=:verdict_id
            """), {"tenant": TENANT, "verdict_id": verdict_id}).scalar_one()
            jobs = connection.execute(text("""
                SELECT count(*) FROM explanation_jobs
                WHERE tenant_id=:tenant AND verdict_id=:verdict_id
            """), {"tenant": TENANT, "verdict_id": verdict_id}).scalar_one()
        assert stored is True
        assert jobs == 0
    finally:
        try:
            _cleanup(admin, ring_id=ring_id, edge_base=edge_base,
                     register_db_test_ids=register_db_test_ids)
        finally:
            admin.dispose()
