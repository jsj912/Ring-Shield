"""PostgreSQL-only RLS acceptance tests. Missing/unreachable DB is a hard failure."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


DB_URL = os.environ.get("RINGSHIELD_DATABASE_URL")
if not DB_URL:
    raise RuntimeError("RINGSHIELD_DATABASE_URL is required; real PostgreSQL RLS tests cannot be skipped")
engine = create_engine(DB_URL, pool_pre_ping=True)
TENANT_A, TENANT_B, TENANT_C = 210, 220, 230


def _tenant_table_security(connection) -> dict[str, tuple[bool, bool, bool]]:
    rows = connection.execute(text("""
        SELECT DISTINCT c.table_name, cls.relrowsecurity, cls.relforcerowsecurity,
               EXISTS (
                   SELECT 1 FROM pg_policies p
                   WHERE p.schemaname = c.table_schema AND p.tablename = c.table_name
               ) AS has_policy
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        JOIN pg_namespace n ON n.nspname = c.table_schema
        JOIN pg_class cls ON cls.relnamespace = n.oid AND cls.relname = c.table_name
        WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id'
          AND t.table_type = 'BASE TABLE'
        ORDER BY c.table_name
    """)).all()
    return {row.table_name: (row.relrowsecurity, row.relforcerowsecurity, row.has_policy) for row in rows}


def _tenant_tables(connection=None) -> list[str]:
    if connection is not None:
        return sorted(_tenant_table_security(connection))
    with engine.connect() as connection:
        return sorted(_tenant_table_security(connection))


def _missing_rls_tables(connection) -> dict[str, list[str]]:
    missing = {}
    for table_name, (enabled, forced, has_policy) in _tenant_table_security(connection).items():
        reasons = []
        if not enabled:
            reasons.append("RLS is disabled")
        if not forced:
            reasons.append("RLS is not forced")
        if not has_policy:
            reasons.append("tenant table has no RLS policy")
        if reasons:
            missing[table_name] = reasons
    return missing


def pytest_generate_tests(metafunc):
    if "tenant_table" in metafunc.fixturenames:
        metafunc.parametrize("tenant_table", _tenant_tables())


@pytest.fixture
def connection():
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


def _set_context(connection, tenant_id: int | None, role: str = "analyst") -> None:
    connection.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                       {"tenant_id": "" if tenant_id is None else str(tenant_id)})
    connection.execute(text("SELECT set_config('app.user_role', :role, true)"), {"role": role})


def test_app_role_is_restricted_and_not_a_table_owner(connection):
    role = connection.execute(text("""
        SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user
    """)).one()
    assert role.rolname == "ringshield_api"
    assert role.rolsuper is False
    assert role.rolbypassrls is False
    owners = list(connection.scalars(text("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tableowner = current_user
    """)))
    assert owners == []


def test_every_tenant_table_has_enabled_and_forced_rls(connection):
    actual = set(_tenant_tables(connection))
    assert actual
    assert _missing_rls_tables(connection) == {}


def test_dynamic_discovery_negative_control_detects_unprotected_tenant_table():
    admin_engine = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    table_name = f"rls_probe_{uuid4().hex[:12]}"
    quote = admin_engine.dialect.identifier_preparer.quote(table_name)
    try:
        with admin_engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f"CREATE TABLE public.{quote} (tenant_id bigint NOT NULL)"))
                assert table_name in _tenant_tables(connection)
                missing = _missing_rls_tables(connection)
                assert table_name in missing
                assert "tenant table has no RLS policy" in missing[table_name]
            finally:
                transaction.rollback()
    finally:
        admin_engine.dispose()


def test_tenant_a_cannot_read_tenant_b_and_no_context_fails_closed(connection, tenant_table):
    quote = engine.dialect.identifier_preparer.quote(tenant_table)
    _set_context(connection, None, role="admin")
    seeded_b = connection.execute(text(f"SELECT count(*) FROM {quote} WHERE tenant_id = :tenant"),
                                  {"tenant": TENANT_B}).scalar_one()
    assert seeded_b > 0, f"fixture must include a tenant B row in {tenant_table}"

    _set_context(connection, TENANT_A)
    visible_b = connection.execute(text(f"SELECT count(*) FROM {quote} WHERE tenant_id = :tenant"),
                                   {"tenant": TENANT_B}).scalar_one()
    assert visible_b == 0

    _set_context(connection, None)
    visible_without_context = connection.execute(text(f"SELECT count(*) FROM {quote}")).scalar_one()
    assert visible_without_context == 0


def test_with_check_rejects_moving_a_ring_to_another_tenant(connection):
    _set_context(connection, TENANT_A)
    with pytest.raises(DBAPIError):
        connection.execute(text("""
            UPDATE rings SET tenant_id = :tenant_b, ring_id = 'rls-moved'
            WHERE tenant_id = :tenant_a AND ring_id = 'demo-cycle'
        """), {"tenant_a": TENANT_A, "tenant_b": TENANT_B})


def test_admin_reads_across_tenants_but_cannot_mutate_verdicts(connection):
    _set_context(connection, None, role="admin")
    assert connection.execute(text("SELECT count(*) FROM accounts WHERE tenant_id IN (210, 220)"))\
        .scalar_one() > 0
    with pytest.raises(DBAPIError):
        with connection.begin_nested():
            connection.execute(text("""
                INSERT INTO verdicts (tenant_id, ring_id, user_id, verdict, corrected_members,
                                     corrected_edges, is_simulated)
                SELECT 210, 'demo-cycle', user_id, 'reject', ARRAY[]::bigint[], ARRAY[]::bigint[], false
                FROM users WHERE tenant_id = 210 LIMIT 1
            """))
    with pytest.raises(DBAPIError):
        with connection.begin_nested():
            connection.execute(text("UPDATE verdicts SET note = 'admin-write' WHERE tenant_id = 210"))
    with pytest.raises(DBAPIError):
        with connection.begin_nested():
            connection.execute(text("DELETE FROM verdicts WHERE tenant_id = 210"))


def test_cross_bank_transaction_is_visible_to_both_endpoint_tenants_only(connection):
    for tenant_id in (TENANT_A, TENANT_B):
        _set_context(connection, tenant_id)
        assert connection.execute(text("""
            SELECT count(*) FROM transactions
            WHERE tenant_id = :tenant_id AND edge_id = 1 AND from_bank = 210 AND to_bank = 220
        """), {"tenant_id": tenant_id}).scalar_one() == 1
    _set_context(connection, TENANT_C)
    assert connection.execute(text("SELECT count(*) FROM transactions WHERE edge_id = 1")).scalar_one() == 0


def test_edge_scores_keeps_rows_from_multiple_models(connection):
    _set_context(connection, TENANT_A)
    rows = connection.execute(text("""
        SELECT model_id, seed, score_raw FROM edge_scores
        WHERE tenant_id = :tenant_id AND edge_id = 1 ORDER BY model_id
    """), {"tenant_id": TENANT_A}).all()
    assert [(row.model_id, row.seed) for row in rows] == [("alternate-model", 99), ("demo-model", 7)]
    assert rows[1].score_raw == pytest.approx(0.97)
