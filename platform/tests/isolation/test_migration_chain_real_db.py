"""Exercise the migration chain against a disposable real PostgreSQL database."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


ADMIN_URL = os.environ.get("RINGSHIELD_DATABASE_ADMIN_URL")
if not ADMIN_URL:
    pytest.skip("RINGSHIELD_DATABASE_ADMIN_URL is required for migration integration tests", allow_module_level=True)

ROOT = Path(__file__).resolve().parents[3]


def _alembic(database_url: str, *args: str) -> None:
    env = os.environ.copy()
    env["RINGSHIELD_MIGRATION_DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "platform/alembic.ini", *args],
        cwd=ROOT,
        env=env,
        check=True,
    )


def test_migration_chain_round_trips_and_enforces_forced_rls():
    admin_url = make_url(ADMIN_URL)
    maintenance_url = admin_url.set(database="postgres")
    database_name = f"ringshield_migration_{uuid4().hex[:12]}"
    maintenance_engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    test_database_url = admin_url.set(database=database_name)
    try:
        with maintenance_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        migration_url = test_database_url.render_as_string(hide_password=False)
        _alembic(migration_url, "upgrade", "0002_role_ownership_force_rls")
        _alembic(migration_url, "upgrade", "head")
        _alembic(migration_url, "downgrade", "base")
        _alembic(migration_url, "upgrade", "head")
        _alembic(migration_url, "check")

        engine = create_engine(test_database_url)
        try:
            with engine.connect() as connection:
                insecure = connection.execute(text("""
                    SELECT c.table_name, cls.relrowsecurity, cls.relforcerowsecurity
                    FROM information_schema.columns c
                    JOIN pg_namespace n ON n.nspname = c.table_schema
                    JOIN pg_class cls ON cls.relnamespace = n.oid AND cls.relname = c.table_name
                    WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id'
                    GROUP BY c.table_name, cls.relrowsecurity, cls.relforcerowsecurity
                    HAVING NOT cls.relrowsecurity OR NOT cls.relforcerowsecurity
                    ORDER BY c.table_name
                """)).all()
                assert insecure == [], f"tenant tables missing enabled/forced RLS: {insecure}"
                tables = connection.execute(text("""
                    SELECT count(DISTINCT table_name)
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND column_name = 'tenant_id'
                """)).scalar_one()
                assert tables > 0, "migration test found no tenant-scoped tables"
                index_defs = dict(connection.execute(text("""
                    SELECT indexname, indexdef FROM pg_indexes
                    WHERE schemaname = 'public' AND indexname IN
                      ('ix_rings_tenant_status_conf', 'ix_verdicts_tenant_ring_created')
                """)))
                assert "confidence DESC" in index_defs["ix_rings_tenant_status_conf"]
                assert "tenant_id, ring_id, created_at DESC" in index_defs[
                    "ix_verdicts_tenant_ring_created"
                ]
                audit_columns = set(connection.execute(text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'audit_log'
                """)).scalars())
                assert {"actor", "request_id"} <= audit_columns
                assert connection.execute(text("SELECT to_regclass('public.experiment_jobs')")).scalar_one() is None
        finally:
            engine.dispose()
    finally:
        maintenance_engine.dispose()
        # Connections used by the migration/test engines have been closed before cleanup.
        with maintenance_engine.connect() as connection:
            connection.execute(text(f' DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
