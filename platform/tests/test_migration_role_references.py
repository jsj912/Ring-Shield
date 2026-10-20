"""Keep migration role references aligned with the CI/bootstrap role definitions."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _role_names_created(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    source = re.sub(r"(?m)^\s*--.*$", "", source)
    return set(re.findall(r"\bCREATE\s+ROLE\s+(ringshield_[a-z0-9_]+)\b", source, re.I))


def _role_references(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    # PostgreSQL role names in this repo are lowercase; uppercase matches are
    # environment variable names such as RINGSHIELD_TEST_ADMIN_URL.
    return set(re.findall(r"\bringshield_[a-z0-9_]+\b", source))


def test_audit_migration_and_related_tests_use_bootstrapped_roles_only():
    migration_dir = ROOT / "platform/db/migrations/versions"
    isolation_dir = ROOT / "platform/tests/isolation"
    role_sources = (
        migration_dir / "0002_role_ownership_force_rls.py",
        ROOT / "platform/db/roles.sql",
        isolation_dir / "provision_migration_role.sql",
        isolation_dir / "provision_test_roles.sql",
    )
    created_roles = set().union(*(_role_names_created(path) for path in role_sources))

    # These are the concrete roles from the migration and CI bootstrap scripts.
    assert created_roles == {
        "ringshield_owner",
        "ringshield_api",
        "ringshield_loader",
        "ringshield_simulator",
        "ringshield_auth",
        "ringshield_test_migrator",
        "ringshield_test_app",
        "ringshield_test_auth",
        "ringshield_test_loader",
        "ringshield_test_simulator",
    }

    migration = migration_dir / "0007_audit_indexes.py"
    assert _role_references(migration) <= created_roles
    migration_text = migration.read_text(encoding="utf-8")
    assert "REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC" in migration_text
    assert "rolname LIKE 'ringshield\\_%' ESCAPE '\\'" in migration_text
    assert "rolname <> audit_owner" in migration_text

    # API/loader grants execute in 0007 before roles.sql creates ringshield_auth.
    roles_from_0002 = _role_names_created(role_sources[0])
    assert {"ringshield_api", "ringshield_loader"} <= roles_from_0002

    for test_path in (
        isolation_dir / "test_audit_log_real_db.py",
        isolation_dir / "test_migration_chain_real_db.py",
        isolation_dir / "seed_rls_fixture.py",
    ):
        references = _role_references(test_path)
        # The migration-chain test uses this prefix for a disposable database,
        # not for a PostgreSQL role.
        references.discard("ringshield_migration_")
        assert references <= created_roles, test_path
