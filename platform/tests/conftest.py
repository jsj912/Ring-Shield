"""Shared test hooks for database-backed platform acceptance checks."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def repo_platform_config(monkeypatch):
    from settings import DEFAULT_CONFIG, load_platform_config

    monkeypatch.setenv("RINGSHIELD_PLATFORM_CONFIG", str(DEFAULT_CONFIG))
    load_platform_config.cache_clear()
    try:
        yield
    finally:
        load_platform_config.cache_clear()


def pytest_sessionstart(session) -> None:
    database_url = os.environ.get("RINGSHIELD_DATABASE_URL")
    if not database_url:
        return
    engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise pytest.UsageError(
            "RINGSHIELD_DATABASE_URL is set but PostgreSQL is unreachable; "
            "database-backed platform tests cannot be skipped"
        ) from exc
    finally:
        engine.dispose()


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    reports = [
        report
        for outcome in ("passed", "failed", "skipped")
        for report in terminalreporter.stats.get(outcome, [])
        if report.when == "call" and "test_rls_real_db.py::" in report.nodeid
        and outcome != "skipped"
    ]
    terminalreporter.write_sep("=", f"RLS_POSTGRES_TESTS_EXECUTED={len(reports)}")
