"""Audit privileges, append-only behavior, and row isolation on real PostgreSQL."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT))

from audit import add_audit_event  # noqa: E402
from db.models import AuditLog  # noqa: E402
from db.session import (  # noqa: E402
    db_session,
    loader_db_session,
    simulator_db_session,
)


def _assert_insert_only_role(role_name: str) -> None:
    engine = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    try:
        with engine.connect() as connection:
            privileges = connection.execute(text("""
                SELECT has_table_privilege(:role, 'audit_log', 'INSERT'),
                       has_table_privilege(:role, 'audit_log', 'SELECT'),
                       has_table_privilege(:role, 'audit_log', 'UPDATE'),
                       has_table_privilege(:role, 'audit_log', 'DELETE')
            """), {"role": role_name}).one()
        assert privileges == (True, False, False, False), (role_name, privileges)
    finally:
        engine.dispose()


def _assert_no_read_or_mutation(session_factory, *, tenant_id: int, object_id: str) -> None:
    statements = (
        "SELECT log_id FROM audit_log WHERE tenant_id=:tenant AND object_id=:object_id",
        "UPDATE audit_log SET action='test.changed' WHERE tenant_id=:tenant AND object_id=:object_id",
        "DELETE FROM audit_log WHERE tenant_id=:tenant AND object_id=:object_id",
    )
    for statement in statements:
        with pytest.raises(DBAPIError):
            with session_factory(tenant_id=tenant_id) as session:
                session.execute(text(statement), {"tenant": tenant_id, "object_id": object_id})


@pytest.mark.parametrize(
    ("role_name", "session_factory", "actor"),
    [
        ("ringshield_loader", loader_db_session, "loader"),
        ("ringshield_simulator", simulator_db_session, "simulator"),
    ],
)
def test_insert_only_audit_roles_are_tenant_bound_and_cannot_read_or_mutate(
        role_name, session_factory, actor, register_db_test_ids):
    tenant_a, tenant_b = 210, 220
    marker = f"audit-test-{uuid4().hex}"
    register_db_test_ids(marker)
    _assert_insert_only_role(role_name)
    try:
        with pytest.raises(DBAPIError):
            with session_factory(tenant_id=tenant_a) as session:
                add_audit_event(session, tenant_id=tenant_b, actor=actor,
                                action="test.cross_tenant", entity_type="test",
                                entity_id=marker, details={})

        with session_factory(tenant_id=tenant_a) as session:
            add_audit_event(session, tenant_id=tenant_a, actor=actor,
                            action="test.tenant_insert", entity_type="test",
                            entity_id=marker, details={})

        _assert_no_read_or_mutation(
            session_factory, tenant_id=tenant_a, object_id=marker
        )
    finally:
        engine = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
        try:
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM audit_log WHERE object_id=:marker"),
                                   {"marker": marker})
        finally:
            engine.dispose()


def test_api_role_reads_only_its_tenant_audit_rows(register_db_test_ids):
    tenant_a, tenant_b = 210, 220
    marker_a = f"audit-api-a-{uuid4().hex}"
    marker_b = f"audit-api-b-{uuid4().hex}"
    register_db_test_ids(marker_a, marker_b)
    try:
        for tenant_id, marker in ((tenant_a, marker_a), (tenant_b, marker_b)):
            with loader_db_session(tenant_id=tenant_id) as session:
                add_audit_event(session, tenant_id=tenant_id, actor="loader",
                                action="test.api_visibility", entity_type="test",
                                entity_id=marker, details={})

        with db_session(tenant_id=tenant_a, role="analyst") as session:
            own_rows = session.scalars(select(AuditLog.object_id).where(
                AuditLog.tenant_id == tenant_a,
                AuditLog.object_id.in_((marker_a, marker_b)),
            )).all()
            cross_tenant_rows = session.scalars(select(AuditLog.object_id).where(
                AuditLog.tenant_id == tenant_b,
                AuditLog.object_id == marker_b,
            )).all()
        assert own_rows == [marker_a]
        assert cross_tenant_rows == []
    finally:
        engine = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
        try:
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM audit_log WHERE object_id IN (:a, :b)"),
                                   {"a": marker_a, "b": marker_b})
        finally:
            engine.dispose()


def test_null_tenant_audit_rows_are_admin_only_and_schema_allows_null(register_db_test_ids):
    tenant_a = 210
    marker = f"audit-null-tenant-{uuid4().hex}"
    rejected_markers = [f"{marker}-{role}" for role in (
        "analyst", "supervisor", "loader", "simulator",
    )]
    register_db_test_ids(marker, *rejected_markers)
    engine = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    try:
        # The nullable ORM mapping must match the migrated schema.
        assert AuditLog.__table__.c.tenant_id.nullable is True
        with engine.connect() as connection:
            tenant_nullable = connection.execute(text("""
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'audit_log'
                  AND column_name = 'tenant_id'
            """)).scalar_one()
        assert tenant_nullable == ("YES" if AuditLog.__table__.c.tenant_id.nullable else "NO")

        # An API administrator may write a global audit row and read it back.
        with db_session(role="admin") as session:
            add_audit_event(session, tenant_id=None, actor="admin",
                            action="test.global_insert", entity_type="test",
                            entity_id=marker, details={})
        with db_session(role="admin") as session:
            admin_rows = session.scalars(select(AuditLog.object_id).where(
                AuditLog.tenant_id.is_(None), AuditLog.object_id == marker,
            )).all()
        assert admin_rows == [marker]

        # Global rows are invisible both without tenant context and from a tenant.
        with db_session(role="analyst") as session:
            no_context_rows = session.scalars(select(AuditLog.object_id).where(
                AuditLog.tenant_id.is_(None), AuditLog.object_id == marker,
            )).all()
        with db_session(tenant_id=tenant_a, role="analyst") as session:
            tenant_rows = session.scalars(select(AuditLog.object_id).where(
                AuditLog.tenant_id.is_(None), AuditLog.object_id == marker,
            )).all()
        assert no_context_rows == []
        assert tenant_rows == []

        # Tenant API roles and both restricted job roles cannot create a global row.
        for role, session_factory in (
            ("analyst", lambda **kwargs: db_session(role="analyst", **kwargs)),
            ("supervisor", lambda **kwargs: db_session(role="supervisor", **kwargs)),
            ("loader", loader_db_session),
            ("simulator", simulator_db_session),
        ):
            with pytest.raises(DBAPIError):
                with session_factory(tenant_id=tenant_a) as session:
                    add_audit_event(
                        session, tenant_id=None, actor=role,
                        action="test.global_rejected", entity_type="test",
                        entity_id=f"{marker}-{role}", details={},
                    )

        # Admin remains read-only for mutations even though it may append rows.
        for statement in (
            "UPDATE audit_log SET action='test.changed' WHERE object_id=:marker",
            "DELETE FROM audit_log WHERE object_id=:marker",
        ):
            with pytest.raises(DBAPIError):
                with db_session(role="admin") as session:
                    session.execute(text(statement), {"marker": marker})
    finally:
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "DELETE FROM audit_log WHERE object_id = :marker "
                    "OR object_id LIKE :rejected_prefix"
                ), {"marker": marker, "rejected_prefix": f"{marker}-%"})
        finally:
            engine.dispose()
