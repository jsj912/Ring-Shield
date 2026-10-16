"""Add valid A/B rows to every platform table carrying a tenant_id."""

from __future__ import annotations

import os

import bcrypt
from sqlalchemy import create_engine, text


def main() -> None:
    url = os.environ.get("RINGSHIELD_TEST_ADMIN_URL")
    if not url:
        raise RuntimeError("RINGSHIELD_TEST_ADMIN_URL is required to load the RLS test fixture")
    fixture_password = "fixture-only-password"
    fixture_password_hash = bcrypt.hashpw(
        fixture_password.encode("utf-8"), bcrypt.gensalt()
    ).decode("ascii")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO users (tenant_id, email, password_hash, role)
            VALUES (NULL, 'admin@test.invalid', :password_hash, 'admin')
        """), {"password_hash": fixture_password_hash})
        users = {}
        for tenant_id in (210, 220):
            connection.execute(text("""
                INSERT INTO edge_scores
                  (tenant_id, edge_id, model_id, seed, score_raw, score_calibrated, is_seed, payload)
                VALUES (:tenant_id, 1, 'alternate-model', 99, 0.01, 0.01, false, '{}')
            """), {"tenant_id": tenant_id})
            result = connection.execute(text("""
                INSERT INTO users (tenant_id, email, password_hash, role)
                VALUES (:tenant_id, :email, :password_hash, 'analyst')
                RETURNING user_id
            """), {"tenant_id": tenant_id, "email": f"analyst-{tenant_id}@test.invalid",
                  "password_hash": fixture_password_hash})
            users[tenant_id] = result.scalar_one()

            connection.execute(text("""
                INSERT INTO explanations
                  (tenant_id, ring_id, explainer_version, edge_weights, account_weights,
                   feature_weights, narrative, evidence_summary, latency_ms, provenance)
                VALUES (:tenant_id, 'demo-cycle', 'rls-fixture', '[]', '[]', '[]',
                        'fixture', '{}', 0, '{}')
            """), {"tenant_id": tenant_id})
            connection.execute(text("""
                INSERT INTO verdicts
                  (tenant_id, ring_id, user_id, verdict, corrected_members, corrected_edges, is_simulated)
                VALUES (:tenant_id, 'demo-cycle', :user_id, 'confirm', ARRAY[]::bigint[],
                        ARRAY[]::bigint[], false)
            """), {"tenant_id": tenant_id, "user_id": users[tenant_id]})
            result = connection.execute(text("""
                INSERT INTO model_versions
                  (tenant_id, component, version_tag, trained_at, train_label_count, promoted)
                VALUES (:tenant_id, 'detector', 'rls-fixture', now(), 0, false)
                RETURNING model_version_id
            """), {"tenant_id": tenant_id})
            version_id = result.scalar_one()
            connection.execute(text("""
                INSERT INTO retrain_runs
                  (run_id, tenant_id, triggered_by, status, model_version_id)
                VALUES (:run_id, :tenant_id, 'supervisor', 'completed', :version_id)
            """), {"run_id": f"fixture-{tenant_id}", "tenant_id": tenant_id,
                  "version_id": version_id})
            connection.execute(text("""
                INSERT INTO drift_events
                  (tenant_id, monitor, detected_at, window_start, window_end, statistic, threshold, acted_on)
                VALUES (:tenant_id, 'adwin_score_mean', now(), now(), now(), 0.1, 0.2, false)
            """), {"tenant_id": tenant_id})
            connection.execute(text("""
                INSERT INTO audit_log (tenant_id, user_id, action, object_type, object_id, details)
                VALUES (:tenant_id, :user_id, 'fixture', 'ring', 'demo-cycle', '{}')
            """), {"tenant_id": tenant_id, "user_id": users[tenant_id]})
    engine.dispose()


if __name__ == "__main__":
    main()
