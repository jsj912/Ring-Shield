"""PostgreSQL checks for explanation-job retry and tenant integrity constraints."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


DB_URL = os.environ.get("RINGSHIELD_TEST_ADMIN_URL")
if not DB_URL:
    raise RuntimeError("RINGSHIELD_TEST_ADMIN_URL is required for explanation job constraint tests")
engine = create_engine(DB_URL, pool_pre_ping=True)


def _ring(connection, tenant_id: int, ring_id: str) -> None:
    connection.execute(text("""
        INSERT INTO rings
          (tenant_id, ring_id, model_id, aggregator_id, seed, scope,
           member_accounts, member_edges, seed_edges, expanded_edges,
           confidence, topology_type, topology_probs, start_time, end_time)
        VALUES (:tenant_id, :ring_id, 'gine_causal', 'full', 1, 'tenant',
                ARRAY[21]::bigint[], ARRAY[17]::bigint[], ARRAY[17]::bigint[],
                ARRAY[]::bigint[], 0.8, 'CYCLE', ARRAY[1.0]::float[], 10, 20)
        ON CONFLICT (tenant_id, ring_id) DO NOTHING
    """), {"tenant_id": tenant_id, "ring_id": ring_id})


def _verdict(connection, tenant_id: int, ring_id: str, user_id: int) -> int:
    return connection.execute(text("""
        INSERT INTO verdicts
          (tenant_id, ring_id, user_id, verdict, corrected_members,
           corrected_edges, is_simulated)
        VALUES (:tenant_id, :ring_id, :user_id, 'confirm',
                ARRAY[]::bigint[], ARRAY[]::bigint[], false)
        RETURNING verdict_id
    """), {"tenant_id": tenant_id, "ring_id": ring_id,
          "user_id": user_id}).scalar_one()


def _job(connection, *, job_id: str, tenant_id: int, ring_id: str,
         verdict_id: int, requested_by: int) -> None:
    connection.execute(text("""
        INSERT INTO explanation_jobs
          (job_id, tenant_id, ring_id, verdict_id, requested_by)
        VALUES (:job_id, :tenant_id, :ring_id, :verdict_id, :requested_by)
    """), {"job_id": job_id, "tenant_id": tenant_id, "ring_id": ring_id,
          "verdict_id": verdict_id, "requested_by": requested_by})


def test_failed_explanation_job_can_be_retried_but_active_job_cannot(
        register_db_test_ids):
    tenant_id = 210
    suffix = uuid4().hex
    ring_id = f"job-retry-{suffix}"
    job_ids = [f"{tenant_id}.{uuid4().hex}" for _ in range(3)]
    register_db_test_ids(ring_id, *job_ids)
    try:
        with engine.begin() as connection:
            _ring(connection, tenant_id, ring_id)
            requested_by = connection.execute(text("""
                SELECT user_id FROM users WHERE tenant_id = :tenant_id
                ORDER BY user_id LIMIT 1
            """), {"tenant_id": tenant_id}).scalar_one()
            verdict_id = _verdict(connection, tenant_id, ring_id, requested_by)
            _job(connection, job_id=job_ids[0], tenant_id=tenant_id, ring_id=ring_id,
                 verdict_id=verdict_id, requested_by=requested_by)
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _job(connection, job_id=job_ids[1], tenant_id=tenant_id, ring_id=ring_id,
                         verdict_id=verdict_id, requested_by=requested_by)
            connection.execute(text("""
                UPDATE explanation_jobs SET status = 'failed'
                WHERE tenant_id = :tenant_id AND job_id = :job_id
            """), {"tenant_id": tenant_id, "job_id": job_ids[0]})
            _job(connection, job_id=job_ids[1], tenant_id=tenant_id, ring_id=ring_id,
                 verdict_id=verdict_id, requested_by=requested_by)
            connection.execute(text("""
                UPDATE explanation_jobs SET status = 'succeeded'
                WHERE tenant_id = :tenant_id AND job_id = :job_id
            """), {"tenant_id": tenant_id, "job_id": job_ids[1]})
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _job(connection, job_id=job_ids[2], tenant_id=tenant_id, ring_id=ring_id,
                         verdict_id=verdict_id, requested_by=requested_by)
    finally:
        with engine.begin() as connection:
            connection.execute(text(
                "DELETE FROM explanation_jobs WHERE tenant_id = :tenant_id AND ring_id = :ring_id"
            ), {"tenant_id": tenant_id, "ring_id": ring_id})
            connection.execute(text(
                "DELETE FROM verdicts WHERE tenant_id = :tenant_id AND ring_id = :ring_id"
            ), {"tenant_id": tenant_id, "ring_id": ring_id})
            connection.execute(text(
                "DELETE FROM rings WHERE tenant_id = :tenant_id AND ring_id = :ring_id"
            ), {"tenant_id": tenant_id, "ring_id": ring_id})
