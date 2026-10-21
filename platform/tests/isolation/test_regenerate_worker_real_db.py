"""Run one regeneration job through the loader role and a local fake L4 server."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from threading import Thread
from uuid import uuid4

from sqlalchemy import create_engine, text

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs.regenerate_worker import _claim, run_job  # noqa: E402

TENANT_A = 210
TENANT_B = 220
FX_HASH = "ee0e8a23b6037e4aeceb44b6874a70d7b46114559551fd2cf94a3842bb8d4ac6"


def _ring_insert(connection, tenant_id: int, ring_id: str) -> None:
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
        ON CONFLICT (tenant_id, ring_id) DO NOTHING
    """), {"tenant_id": tenant_id, "ring_id": ring_id})


def _fake_l4_handler(token: str, received: list[dict]):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/regenerate"
            assert self.headers.get("Authorization") == f"Bearer {token}"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(body)
            provenance = {
                "scope": "tenant", "tenant_id": body["tenant_id"],
                "feature_scope": "tenant_view", "fx_rates_sha256": FX_HASH,
                "rings_schema_version": 1, "explainer_version": "0.5.0-review",
                "regenerated": True, "excluded_members": body["excluded_members"],
                "excluded_edges": body["excluded_edges"],
            }
            response = {
                **body, "explainer_version": "0.5.0-review",
                "edge_weights": [{"edge_id": 18, "weight": 0.7}],
                "account_weights": [{"account_id": 22, "weight": 1.0}],
                "feature_weights": [], "narrative": "Corrected tenant explanation",
                "evidence_summary": json.dumps({"template": "CYCLE"}),
                "latency_ms": 6, "provenance": json.dumps(provenance),
            }
            encoded = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):
            return

    return Handler


def test_worker_runs_job_as_loader_and_preserves_other_tenant_rows(
        monkeypatch, register_db_test_ids):
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    suffix = uuid4().hex
    ring_id = f"regen-{suffix}"
    job_id = f"{TENANT_A}.{uuid4().hex}"
    verdict_id = int(suffix[:12], 16)
    register_db_test_ids(ring_id, job_id)
    token = f"test-token-{suffix}"
    received: list[dict] = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _fake_l4_handler(token, received))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with admin.begin() as connection:
            _ring_insert(connection, TENANT_A, ring_id)
            _ring_insert(connection, TENANT_B, ring_id)
            requested_by = connection.execute(text("""
                SELECT user_id FROM users WHERE tenant_id = :tenant_id
                ORDER BY user_id LIMIT 1
            """), {"tenant_id": TENANT_A}).scalar_one()
            for tenant_id, narrative in ((TENANT_A, "Tenant A original"),
                                         (TENANT_B, "Other tenant original")):
                connection.execute(text("""
                    INSERT INTO explanations
                      (tenant_id, ring_id, explainer_version, revision, edge_weights,
                       account_weights, feature_weights, narrative, evidence_summary,
                       latency_ms, provenance, fx_rates_sha256)
                    VALUES (:tenant_id, :ring_id, '0.5.0-review', 1, '[]', '[]', '[]',
                            :narrative, '{}', 1, '{}', :fx_hash)
                """), {"tenant_id": tenant_id, "ring_id": ring_id,
                      "narrative": narrative, "fx_hash": FX_HASH})
            connection.execute(text("""
                INSERT INTO explanation_jobs
                  (job_id, tenant_id, ring_id, verdict_id, requested_by,
                   excluded_members, excluded_edges)
                VALUES (:job_id, :tenant_id, :ring_id, :verdict_id, :requested_by,
                        ARRAY[21]::bigint[], ARRAY[17]::bigint[])
            """), {"job_id": job_id, "tenant_id": TENANT_A, "ring_id": ring_id,
                  "verdict_id": verdict_id, "requested_by": requested_by})

        monkeypatch.setenv("RINGSHIELD_XAI_TOKEN", token)
        config = {"fx_rates_sha256": FX_HASH, "l4": {
            "rings_schema_version": 1,
            "regenerate_url": f"http://127.0.0.1:{server.server_port}",
            "regenerate_timeout_seconds": 5,
        }}
        assert run_job(job_id, config=config)
        assert received == [{"tenant_id": TENANT_A, "ring_id": ring_id,
                             "excluded_members": [21], "excluded_edges": [17]}]

        with admin.connect() as connection:
            job = connection.execute(text("""
                SELECT status, result_revision FROM explanation_jobs
                WHERE tenant_id = :tenant_id AND job_id = :job_id
            """), {"tenant_id": TENANT_A, "job_id": job_id}).one()
            revision = connection.execute(text("""
                SELECT revision, narrative FROM explanations
                WHERE tenant_id = :tenant_id AND ring_id = :ring_id
                  AND explainer_version = '0.5.0-review'
                ORDER BY revision DESC LIMIT 1
            """), {"tenant_id": TENANT_A, "ring_id": ring_id}).one()
            other = connection.execute(text("""
                SELECT revision, narrative FROM explanations
                WHERE tenant_id = :tenant_id AND ring_id = :ring_id
            """), {"tenant_id": TENANT_B, "ring_id": ring_id}).one()
            audit = connection.execute(text("""
                SELECT action, details->>'revision' FROM audit_log
                WHERE tenant_id = :tenant_id AND object_id = :job_id
            """), {"tenant_id": TENANT_A, "job_id": job_id}).one()
        assert job == ("succeeded", 2)
        assert revision == (2, "Corrected tenant explanation")
        assert other == (1, "Other tenant original")
        assert audit == ("explanation.regeneration_succeeded", "2")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        with admin.begin() as connection:
            connection.execute(text("DELETE FROM audit_log WHERE tenant_id = :tenant_id AND object_id = :job_id"),
                               {"tenant_id": TENANT_A, "job_id": job_id})
            connection.execute(text("DELETE FROM explanation_jobs WHERE tenant_id = :tenant_id AND job_id = :job_id"),
                               {"tenant_id": TENANT_A, "job_id": job_id})
            connection.execute(text("DELETE FROM explanations WHERE ring_id = :ring_id"),
                               {"ring_id": ring_id})
            connection.execute(text("DELETE FROM rings WHERE ring_id = :ring_id"),
                               {"ring_id": ring_id})
        admin.dispose()


def test_locked_queued_job_is_skipped_by_second_worker(register_db_test_ids):
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    ring_id = f"regen-lock-{uuid4().hex}"
    job_id = f"{TENANT_A}.{uuid4().hex}"
    register_db_test_ids(ring_id, job_id)
    try:
        with admin.begin() as connection:
            _ring_insert(connection, TENANT_A, ring_id)
            requested_by = connection.execute(text("""
                SELECT user_id FROM users WHERE tenant_id = :tenant_id
                ORDER BY user_id LIMIT 1
            """), {"tenant_id": TENANT_A}).scalar_one()
            connection.execute(text("""
                INSERT INTO explanation_jobs
                  (job_id, tenant_id, ring_id, verdict_id, requested_by)
                VALUES (:job_id, :tenant_id, :ring_id, :verdict_id, :requested_by)
            """), {"job_id": job_id, "tenant_id": TENANT_A, "ring_id": ring_id,
                  "verdict_id": int(uuid4().hex[:12], 16), "requested_by": requested_by})

        with admin.begin() as connection:
            connection.execute(text("""
                SELECT job_id FROM explanation_jobs
                WHERE tenant_id = :tenant_id AND job_id = :job_id FOR UPDATE
            """), {"tenant_id": TENANT_A, "job_id": job_id}).one()
            assert _claim(TENANT_A, job_id) is None
    finally:
        with admin.begin() as connection:
            connection.execute(text("DELETE FROM explanation_jobs WHERE tenant_id = :tenant_id AND job_id = :job_id"),
                               {"tenant_id": TENANT_A, "job_id": job_id})
            connection.execute(text("DELETE FROM rings WHERE tenant_id = :tenant_id AND ring_id = :ring_id"),
                               {"tenant_id": TENANT_A, "ring_id": ring_id})
        admin.dispose()
