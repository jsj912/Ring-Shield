"""Database sessions with transaction-local tenant and role context."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_sessions: sessionmaker[Session] | None = None
_auth_engine: Engine | None = None
_auth_sessions: sessionmaker[Session] | None = None
_loader_engine: Engine | None = None
_loader_sessions: sessionmaker[Session] | None = None
_simulator_engine: Engine | None = None
_simulator_sessions: sessionmaker[Session] | None = None
_simulator_engine: Engine | None = None
_simulator_sessions: sessionmaker[Session] | None = None

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def get_engine() -> Engine:
    global _engine, _sessions
    if _engine is None:
        url = os.environ.get("RINGSHIELD_DATABASE_URL")
        if not url:
            raise RuntimeError("RINGSHIELD_DATABASE_URL is not configured")
        _engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)
        _sessions = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_auth_engine() -> Engine:
    global _auth_engine, _auth_sessions
    if _auth_engine is None:
        url = os.environ.get("RINGSHIELD_AUTH_DATABASE_URL")
        if not url:
            raise RuntimeError("RINGSHIELD_AUTH_DATABASE_URL is not configured")
        _auth_engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3)
        _auth_sessions = sessionmaker(bind=_auth_engine, expire_on_commit=False)
    return _auth_engine


def get_loader_engine() -> Engine:
    global _loader_engine, _loader_sessions
    if _loader_engine is None:
        url = os.environ.get("RINGSHIELD_LOADER_DATABASE_URL")
        if not url:
            raise RuntimeError("RINGSHIELD_LOADER_DATABASE_URL is not configured")
        _loader_engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3)
        _loader_sessions = sessionmaker(bind=_loader_engine, expire_on_commit=False)
    return _loader_engine


def get_simulator_engine() -> Engine:
    global _simulator_engine, _simulator_sessions
    if _simulator_engine is None:
        url = os.environ.get("RINGSHIELD_SIMULATOR_DATABASE_URL")
        if not url:
            raise RuntimeError("RINGSHIELD_SIMULATOR_DATABASE_URL is not configured")
        _simulator_engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3)
        _simulator_sessions = sessionmaker(bind=_simulator_engine, expire_on_commit=False)
    return _simulator_engine


def get_simulator_engine() -> Engine:
    global _simulator_engine, _simulator_sessions
    if _simulator_engine is None:
        url = os.environ.get("RINGSHIELD_SIMULATOR_DATABASE_URL")
        if not url:
            raise RuntimeError("RINGSHIELD_SIMULATOR_DATABASE_URL is not configured")
        _simulator_engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3)
        _simulator_sessions = sessionmaker(bind=_simulator_engine, expire_on_commit=False)
    return _simulator_engine


@contextmanager
def db_session(*, tenant_id: int | None = None, role: str | None = None) -> Iterator[Session]:
    """Open one transaction and set RLS context before any tenant query.

    The values must come from verified server-side identity, never request body or
    query parameters. `SET LOCAL` semantics are provided by `set_config(..., true)`.
    """
    get_engine()
    assert _sessions is not None
    with _sessions() as session:
        with session.begin():
            if tenant_id is not None:
                session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(int(tenant_id))},
                )
            if role is not None:
                session.execute(
                    text("SELECT set_config('app.user_role', :role, true)"),
                    {"role": role},
                )
            yield session


def check_database() -> None:
    with db_session() as session:
        session.execute(text("SELECT 1"))


@contextmanager
def auth_db_session() -> Iterator[Session]:
    """Use the separate credential-lookup role, which cannot read ring data."""
    get_auth_engine()
    assert _auth_sessions is not None
    with _auth_sessions() as session:
        with session.begin():
            session.execute(text("SELECT set_config('app.user_role', 'auth', true)"))
            yield session


@contextmanager
def loader_db_session() -> Iterator[Session]:
    """Use the separate restricted ingestion role for contract loading."""
    get_loader_engine()
    assert _loader_sessions is not None
    with _loader_sessions() as session:
        with session.begin():
            session.execute(text("SELECT set_config('app.user_role', 'loader', true)"))
            yield session


@contextmanager
def simulator_db_session(*, tenant_id: int) -> Iterator[Session]:
    """Use the restricted simulator database role with transaction-local tenant scope."""
    get_simulator_engine()
    assert _simulator_sessions is not None
    with _simulator_sessions() as session:
        with session.begin():
            session.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                            {"tenant_id": str(int(tenant_id))})
            session.execute(text("SELECT set_config('app.user_role', 'analyst', true)"))
            yield session


@contextmanager
def simulator_db_session(*, tenant_id: int) -> Iterator[Session]:
    """Use the restricted simulator role with transaction-local tenant scope."""
    get_simulator_engine()
    assert _simulator_sessions is not None
    with _simulator_sessions() as session:
        with session.begin():
            session.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                            {"tenant_id": str(int(tenant_id))})
            # This role is additionally constrained by the simulator-specific DB
            # grants and the verdicts_simulator_insert RLS policy.
            session.execute(text("SELECT set_config('app.user_role', 'analyst', true)"))
            yield session
