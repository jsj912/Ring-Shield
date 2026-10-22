"""Run queued regeneration work through the restricted-role supervisor and fake L4."""

from __future__ import annotations

from pathlib import Path
import os
import sys
from threading import Thread
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(0, str(REPO_ROOT))

from jobs.worker_supervisor import WorkItem, collect_pending_work, run_supervisor  # noqa: E402
from scripts.fake_l4_server import create_server  # noqa: E402
from settings import load_platform_config  # noqa: E402


TENANTS = (210, 220)


def _insert_ring(connection, tenant_id: int, ring_id: str) -> None:
    connection.execute(text("""
        INSERT INTO rings
          (tenant_id, ring_id, model_id, aggregator_id, seed, scope,
           member_accounts, member_edges, seed_edges, expanded_edges,
           confidence, topology_type, topology_probs, start_time, end_time,
           status, payload)
        VALUES (:tenant_id, :ring_id, 'gine_causal', 'full', 1, 'tenant',
                ARRAY[21,22]::bigint[], ARRAY[17,18]::bigint[],
                ARRAY[17]::bigint[], ARRAY[18]::bigint[], 0.8, 'CYCLE',
                ARRAY[1.0]::float[], 10, 20, 'open', '{}'::jsonb)
    """), {"tenant_id": tenant_id, "ring_id": ring_id})


def _insert_verdict(connection, tenant_id: int, ring_id: str, user_id: int) -> int:
    return connection.execute(text("""
        INSERT INTO verdicts
          (tenant_id, ring_id, user_id, verdict, corrected_members,
           corrected_edges, is_simulated)
        VALUES (:tenant_id, :ring_id, :user_id, 'confirm',
                ARRAY[]::bigint[], ARRAY[]::bigint[], false)
        RETURNING verdict_id
    """), {"tenant_id": tenant_id, "ring_id": ring_id,
          "user_id": user_id}).scalar_one()


def test_supervisor_once_processes_two_tenants_with_scoped_loader_context(
        monkeypatch, register_db_test_ids, repo_platform_config):
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    suffix = uuid4().hex
    ring_id = f"supervisor-{suffix}"
    job_ids = {tenant: f"{tenant}.{uuid4().hex}" for tenant in TENANTS}
    verdict_ids: list[int] = []
    register_db_test_ids(ring_id, *job_ids.values())
    token = f"supervisor-test-{suffix}"
    config = load_platform_config()
    received: list[dict] = []
    server = create_server(port=0, token=token, config=config, received=received)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Always attempt cleanup from finally, including a partial setup failure.
        with admin.begin() as connection:
            for tenant_id in TENANTS:
                _insert_ring(connection, tenant_id, ring_id)
                user_id = connection.execute(text("""
                    SELECT user_id FROM users WHERE tenant_id = :tenant_id
                    ORDER BY user_id LIMIT 1
                """), {"tenant_id": tenant_id}).scalar_one()
                verdict_id = _insert_verdict(connection, tenant_id, ring_id, user_id)
                verdict_ids.append(verdict_id)
                register_db_test_ids(str(verdict_id))
                connection.execute(text("""
                    INSERT INTO explanation_jobs
                      (job_id, tenant_id, ring_id, verdict_id, requested_by,
                       excluded_members, excluded_edges)
                    VALUES (:job_id, :tenant_id, :ring_id, :verdict_id, :requested_by,
                            ARRAY[21]::bigint[], ARRAY[17]::bigint[])
                """), {"job_id": job_ids[tenant_id], "tenant_id": tenant_id,
                      "ring_id": ring_id, "verdict_id": verdict_id,
                      "requested_by": user_id})
        monkeypatch.setenv("RINGSHIELD_XAI_TOKEN", token)
        monkeypatch.setenv("RINGSHIELD_L4_REGENERATE_URL",
                           f"http://127.0.0.1:{server.server_port}/regenerate")
        monkeypatch.setenv("RINGSHIELD_WORKER_MODE", "supervisor")

        def own_jobs_only() -> list[WorkItem]:
            return [item for item in collect_pending_work(tenants=list(TENANTS))
                    if item.job_id in set(job_ids.values())]

        run_supervisor(once=True, max_concurrent=2, pending_work=own_jobs_only)

        with admin.connect() as connection:
            statuses = connection.execute(text("""
                SELECT tenant_id, status, result_revision FROM explanation_jobs
                WHERE job_id IN (:job_a, :job_b) ORDER BY tenant_id
            """), {"job_a": job_ids[TENANTS[0]], "job_b": job_ids[TENANTS[1]]}).all()
            revisions = connection.execute(text("""
                SELECT tenant_id, ring_id, revision, narrative FROM explanations
                WHERE tenant_id IN (:tenant_a, :tenant_b) AND ring_id = :ring_id
                ORDER BY tenant_id
            """), {"tenant_a": TENANTS[0], "tenant_b": TENANTS[1],
                  "ring_id": ring_id}).all()
        assert statuses == [(TENANTS[0], "succeeded", 1), (TENANTS[1], "succeeded", 1)]
        assert [(row[0], row[1], row[2]) for row in revisions] == [
            (TENANTS[0], ring_id, 1), (TENANTS[1], ring_id, 1),
        ]
        assert all("DEMO STUB" in row[3] for row in revisions)
        assert {body["tenant_id"] for body in received} == set(TENANTS)
        assert len(received) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        with admin.begin() as connection:
            connection.execute(text("DELETE FROM explanation_jobs WHERE job_id IN (:job_a, :job_b)"),
                               {"job_a": job_ids[TENANTS[0]], "job_b": job_ids[TENANTS[1]]})
            connection.execute(text("DELETE FROM explanations WHERE tenant_id IN (:tenant_a, :tenant_b) AND ring_id = :ring_id"),
                               {"tenant_a": TENANTS[0], "tenant_b": TENANTS[1], "ring_id": ring_id})
            connection.execute(text("DELETE FROM audit_log WHERE tenant_id IN (:tenant_a, :tenant_b) AND object_id IN (:job_a, :job_b)"),
                               {"tenant_a": TENANTS[0], "tenant_b": TENANTS[1],
                                "job_a": job_ids[TENANTS[0]], "job_b": job_ids[TENANTS[1]]})
            if verdict_ids:
                connection.execute(text("DELETE FROM verdicts WHERE verdict_id IN (:verdict_a, :verdict_b)"),
                                   {"verdict_a": verdict_ids[0], "verdict_b": verdict_ids[-1]})
            connection.execute(text("DELETE FROM rings WHERE tenant_id IN (:tenant_a, :tenant_b) AND ring_id = :ring_id"),
                               {"tenant_a": TENANTS[0], "tenant_b": TENANTS[1], "ring_id": ring_id})
        admin.dispose()
