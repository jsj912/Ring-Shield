"""Guard cleanup registration for shared-database integration tests."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ISOLATION_DIR = Path(__file__).resolve().parent / "isolation"
DATABASE_WRITE_CALLS = {
    "add_audit_event",
    "load_edges",
    "load_explanations",
    "load_rings",
    "persist_events",
    "refresh_tenant_rings",
    "run_retrain_job",
}
SQL_WRITE = re.compile(r"\b(?:INSERT\s+INTO|UPDATE\s+\w+|DELETE\s+FROM)\b", re.I)


def _calls(node: ast.AST) -> set[str]:
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                names.add(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                names.add(child.func.attr)
    return names


def test_shared_database_integration_writes_register_cleanup_ids():
    """New persistent integration writes must participate in the session leak check."""
    violations = []
    for path in sorted(ISOLATION_DIR.glob("test_*.py")):
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            body_source = ast.get_source_segment(source, node) or ""
            writes_database = bool(SQL_WRITE.search(body_source)) or bool(
                _calls(node) & DATABASE_WRITE_CALLS
            )
            if not writes_database:
                continue

            fixture_names = {
                argument.arg
                for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
            }
            if ("register_db_test_ids" in fixture_names
                    and "register_db_test_ids" in _calls(node)):
                continue

            # These tests own a disposable database and drop it in their finally block;
            # their rows cannot leak into the shared CI database checked by the fixture.
            if (path.name == "test_migration_chain_real_db.py"
                    and "CREATE DATABASE" in source
                    and "DROP DATABASE IF EXISTS" in source):
                continue
            if (path.name == "test_rls_real_db.py"
                    and ("connection" in fixture_names or "transaction.rollback()" in body_source)):
                continue
            violations.append(f"{path.name}::{node.name}")

    assert violations == [], (
        "shared-database integration tests that write rows must request and call "
        "register_db_test_ids: " + ", ".join(violations)
    )


def test_explanation_job_tests_register_ids_and_delete_jobs():
    """Per-test explanation jobs must be registered and removed by teardown."""
    violations = []
    for path in sorted(ISOLATION_DIR.glob("test_*.py")):
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        has_job_insert = bool(re.search(r"\bINSERT\s+INTO\s+explanation_jobs\b", source, re.I))
        if not has_job_insert:
            continue
        if "register_db_test_ids" not in source:
            violations.append(f"{path.name}: missing identifier registration")
        if not re.search(r"\bDELETE\s+FROM\s+explanation_jobs\b", source, re.I):
            violations.append(f"{path.name}: missing job cleanup")

        test_functions = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ]
        if not test_functions:
            violations.append(f"{path.name}: job insert has no test-owned cleanup")

    assert violations == [], (
        "isolation explanation-job inserts must use register_db_test_ids and delete "
        "their rows in cleanup: " + "; ".join(violations)
    )


def test_database_leak_guard_uses_exact_registered_identifier_columns():
    source = (ISOLATION_DIR / "conftest.py").read_text(encoding="utf-8-sig")
    for column in ("run_id", "version_tag", "ring_id", "object_id", "job_id", "verdict_id"):
        assert f"'{column}'" in source
    assert "{quoted_column}::text = :identifier" in source
    assert "row_to_json(row_data)" not in source
