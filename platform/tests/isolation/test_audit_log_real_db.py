"""Audit table write privileges and tenant row policy on real PostgreSQL."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy import select, func
from sqlalchemy.exc import DBAPIError

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT))

from db.models import AuditLog  # noqa: E402
from db.session import loader_db_session, simulator_db_session  # noqa: E402


def test_loader_audit_insert_is_tenant_bound_and_append_only(register_db_test_ids):
    tenant_a, tenant_b = 210, 220
    marker = f"audit-test-{uuid4().hex}"
    register_db_test_ids(marker)

    admin_engine = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    try:
        with admin_engine.connect() as connection:
            grants = connection.execute(text("""
                SELECT role_name,
                       has_table_privilege(role_name, 'audit_log', 'INSERT'),
                       has_table_privilege(role_name, 'audit_log', 'UPDATE'),
                       has_table_privilege(role_name, 'audit_log', 'DELETE')
                FROM unnest(ARRAY['ringshield_api','ringshield_loader','ringshield_simulator']) AS roles(role_name)
            """)).all()
        assert all(can_insert and not can_update and not can_delete
                   for _role, can_insert, can_update, can_delete in grants), grants
    finally:
        admin_engine.dispose()

    with pytest.raises(DBAPIError):
        with loader_db_session(tenant_id=tenant_a) as session:
            session.add(AuditLog(tenant_id=tenant_b, actor="loader", action="test.cross_tenant",
                                 object_type="test", object_id=marker, details={}))
            session.flush()

    log_id = None
    try:
        with loader_db_session(tenant_id=tenant_a) as session:
            row = AuditLog(tenant_id=tenant_a, actor="loader", action="test.tenant_insert",
                           object_type="test", object_id=marker, details={})
            session.add(row)
            session.flush()
            log_id = row.log_id
        with loader_db_session(tenant_id=tenant_a) as session:
            assert session.scalar(select(func.count()).select_from(AuditLog).where(
                AuditLog.tenant_id == tenant_b
            )) == 0
        with pytest.raises(DBAPIError):
            with loader_db_session(tenant_id=tenant_a) as session:
                session.execute(text("UPDATE audit_log SET action='test.changed' WHERE log_id=:id"),
                                {"id": log_id})
        with pytest.raises(DBAPIError):
            with loader_db_session(tenant_id=tenant_a) as session:
                session.execute(text("DELETE FROM audit_log WHERE log_id=:id"), {"id": log_id})
    finally:
        if log_id is not None:
            admin_url = os.environ["RINGSHIELD_TEST_ADMIN_URL"]
            engine = create_engine(admin_url)
            try:
                with engine.begin() as connection:
                    connection.execute(text("DELETE FROM audit_log WHERE log_id=:id"), {"id": log_id})
            finally:
                engine.dispose()


def test_simulator_audit_insert_is_tenant_bound(register_db_test_ids):
    tenant_a, tenant_b = 210, 220
    marker = f"sim-audit-test-{uuid4().hex}"
    register_db_test_ids(marker)
    log_id = None
    try:
        with pytest.raises(DBAPIError):
            with simulator_db_session(tenant_id=tenant_a) as session:
                session.add(AuditLog(tenant_id=tenant_b, actor="simulator",
                                     action="test.cross_tenant", object_type="test",
                                     object_id=marker, details={}))
                session.flush()
        with simulator_db_session(tenant_id=tenant_a) as session:
            row = AuditLog(tenant_id=tenant_a, actor="simulator",
                           action="test.tenant_insert", object_type="test",
                           object_id=marker, details={})
            session.add(row)
            session.flush()
            log_id = row.log_id
    finally:
        if log_id is not None:
            engine = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
            try:
                with engine.begin() as connection:
                    connection.execute(text("DELETE FROM audit_log WHERE log_id=:id"), {"id": log_id})
            finally:
                engine.dispose()
