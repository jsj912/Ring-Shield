"""Create or reset local demo logins and audit them in the same transaction."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import bcrypt
from sqlalchemy import create_engine, text

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from audit import add_audit_event  # noqa: E402


def _write_credentials(path: str | Path, credentials: dict[str, str]) -> None:
    """Persist the supplied credentials without writing them to process output."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    contents = "\n".join(f"{key}={value}" for key, value in credentials.items()) + "\n"
    temporary.write_text(contents, encoding="utf-8")
    temporary.replace(destination)


def _provision_users(connection, users: list[dict], *, password_reset: bool) -> None:
    for user in users:
        tenant_id = None if user["TenantId"] == "None" else int(user["TenantId"])
        digest = bcrypt.hashpw(user["Password"].encode("utf-8"), bcrypt.gensalt()).decode("ascii")
        parameters = {
            "tenant_id": tenant_id,
            "email": user["Email"],
            "password_hash": digest,
            "role": user["Role"],
        }
        if password_reset:
            saved_user = connection.execute(text("""
                INSERT INTO users (tenant_id, email, password_hash, role, disabled)
                VALUES (:tenant_id, :email, :password_hash, :role, false)
                ON CONFLICT (email) DO UPDATE SET password_hash=EXCLUDED.password_hash
                RETURNING user_id, tenant_id
            """), parameters).mappings().one()
            action = "user.password_reset"
        else:
            saved_user = connection.execute(text("""
                INSERT INTO users (tenant_id, email, password_hash, role, disabled)
                VALUES (:tenant_id, :email, :password_hash, :role, false)
                ON CONFLICT (email) DO UPDATE SET tenant_id=EXCLUDED.tenant_id,
                    password_hash=EXCLUDED.password_hash, role=EXCLUDED.role, disabled=false
                RETURNING user_id, tenant_id
            """), parameters).mappings().one()
            action = "user.credentials_initialized"

        saved_tenant_id = saved_user["tenant_id"]
        if saved_tenant_id is not None:
            connection.execute(text("""
                SELECT set_config('app.tenant_id', :tenant_id, true),
                       set_config('app.user_role', 'admin', true)
            """), {"tenant_id": str(saved_tenant_id)})
        else:
            connection.execute(text("SELECT set_config('app.user_role', 'admin', true)"))
        add_audit_event(
            connection,
            tenant_id=saved_tenant_id,
            user_id=int(saved_user["user_id"]),
            actor="demo_bootstrap",
            action=action,
            entity_type="user",
            entity_id=int(saved_user["user_id"]),
            details={"role": user["Role"]},
        )


def main() -> None:
    users = json.loads(os.environ["RINGSHIELD_DEMO_USERS_JSON"])
    credentials = json.loads(os.environ["RINGSHIELD_DEMO_CREDENTIALS_JSON"])
    password_reset = os.environ.get("RINGSHIELD_DEMO_PASSWORD_RESET") == "1"
    engine = create_engine(os.environ["RINGSHIELD_DEMO_ADMIN_URL"])
    try:
        with engine.begin() as connection:
            _provision_users(connection, users, password_reset=password_reset)
        _write_credentials(os.environ["RINGSHIELD_DEMO_CREDENTIALS_PATH"], credentials)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
