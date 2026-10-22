"""Compile the full Alembic chain without connecting to PostgreSQL."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from db.models import ExplanationJob


ROOT = Path(__file__).resolve().parents[2]


def _offline_sql(direction: str, revision_range: str) -> str:
    env = os.environ.copy()
    env["RINGSHIELD_MIGRATION_DATABASE_URL"] = (
        "postgresql+psycopg://offline:offline@127.0.0.1/ringshield"
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "platform/alembic.ini",
         direction, revision_range, "--sql"],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_full_migration_chain_compiles_upgrade_and_downgrade_offline():
    upgrade = _offline_sql("upgrade", "head")
    downgrade = _offline_sql("downgrade", "head:base")

    marker = "-- Running upgrade 0008_ring_member_search -> 0009_explanation_revisions_jobs"
    migration_sql = upgrade.split(marker, maxsplit=1)[1].split(
        "UPDATE alembic_version", maxsplit=1,
    )[0]
    normalized = " ".join(migration_sql.split())
    assert "ALTER TABLE explanations ADD COLUMN revision INTEGER DEFAULT 1 NOT NULL" in normalized
    assert "ALTER TABLE explanations ALTER COLUMN created_at SET DEFAULT clock_timestamp()" in normalized
    assert ("PRIMARY KEY (tenant_id, ring_id, explainer_version, revision)" in normalized)
    assert "CREATE TABLE explanation_jobs" in normalized
    assert ("CONSTRAINT pk_explanation_jobs PRIMARY KEY (job_id)" in normalized)
    assert ("CONSTRAINT fk_explanation_jobs_tenant_ring FOREIGN KEY(tenant_id, ring_id) "
            "REFERENCES rings (tenant_id, ring_id) ON DELETE CASCADE" in normalized)
    assert ("CONSTRAINT fk_explanation_jobs_tenant_user FOREIGN KEY(tenant_id, requested_by) "
            "REFERENCES users (tenant_id, user_id)" in normalized)
    assert ("CREATE UNIQUE INDEX uq_explanation_jobs_active_verdict "
            "ON explanation_jobs (tenant_id, verdict_id) "
            "WHERE status IN ('queued', 'running', 'succeeded')" in normalized)
    assert "UPDATE explanations" not in normalized
    assert "REVOKE ALL ON explanation_jobs FROM PUBLIC" in normalized
    assert "GRANT SELECT, INSERT ON explanation_jobs TO ringshield_api" in normalized
    assert "GRANT SELECT, UPDATE ON explanation_jobs TO ringshield_loader" in normalized

    assert "DROP TABLE IF EXISTS explanation_jobs" in downgrade
    assert "DROP CONSTRAINT IF EXISTS explanations_pkey" in downgrade
    assert "DROP COLUMN IF EXISTS revision" in downgrade
    assert "ALTER TABLE explanations ALTER COLUMN created_at SET DEFAULT now()" in downgrade

    table = ExplanationJob.__table__
    assert table.primary_key.name == "pk_explanation_jobs"
    active_verdict_index = next(
        index for index in table.indexes
        if index.name == "uq_explanation_jobs_active_verdict"
    )
    assert active_verdict_index.unique is True
    assert str(active_verdict_index.dialect_options["postgresql"]["where"]) == (
        "status IN ('queued', 'running', 'succeeded')"
    )
    assert {fk.name: tuple(element.target_fullname for element in fk.elements)
            for fk in table.foreign_key_constraints} == {
        "fk_explanation_jobs_tenant_ring": ("rings.tenant_id", "rings.ring_id"),
        "fk_explanation_jobs_tenant_user": ("users.tenant_id", "users.user_id"),
    }
