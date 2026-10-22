"""Isolation-suite cleanup sentinels for database-backed tests."""

from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import create_engine, text


@pytest.fixture
def register_db_test_ids(request):
    """Register run tokens that must not remain in the test database at session end."""
    identifiers = request.config.__dict__.setdefault("_ringshield_db_test_ids", set())

    def register(*values: str) -> None:
        identifiers.update(str(value) for value in values if value)

    return register


def pytest_sessionfinish(session, exitstatus) -> None:
    identifiers = sorted(session.config.__dict__.get("_ringshield_db_test_ids", set()))
    if not identifiers:
        return
    admin_url = os.environ.get("RINGSHIELD_TEST_ADMIN_URL")
    if not admin_url:
        print("DB test leak check failed: RINGSHIELD_TEST_ADMIN_URL is not configured", file=sys.stderr)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        return

    engine = create_engine(admin_url, pool_pre_ping=True)
    leaks: list[tuple[str, str]] = []
    try:
        with engine.connect() as connection:
            searchable_columns = tuple(connection.execute(text("""
                SELECT DISTINCT c.table_name, c.column_name
                FROM information_schema.columns AS c
                JOIN information_schema.tables AS t
                  ON t.table_schema = c.table_schema AND t.table_name = c.table_name
                WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
                  AND c.column_name IN (
                    'run_id', 'version_tag', 'ring_id', 'object_id', 'job_id', 'verdict_id'
                  )
                ORDER BY c.table_name, c.column_name
            """)).all())
            quote = engine.dialect.identifier_preparer.quote
            for table, column in searchable_columns:
                quoted_table = quote(table)
                quoted_column = quote(column)
                for identifier in identifiers:
                    found = connection.execute(text(
                        f"SELECT 1 FROM public.{quoted_table} "
                        f"WHERE {quoted_column}::text = :identifier LIMIT 1"
                    ), {"identifier": identifier}).first()
                    if found:
                        leaks.append((table, identifier))
    except Exception as exc:
        print(f"DB test leak check could not query PostgreSQL: {type(exc).__name__}: {exc}", file=sys.stderr)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        return
    finally:
        engine.dispose()

    if leaks:
        print(f"DB test rows remain for registered identifiers: {leaks}", file=sys.stderr)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
