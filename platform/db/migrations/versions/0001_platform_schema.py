"""Initial tenant-scoped platform schema and row-level security."""

from alembic import op

from db.base import Base
from db import models  # noqa: F401 - register metadata

revision = "0001_platform_schema"
down_revision = None
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "users", "accounts", "transactions", "rings", "explanations", "verdicts",
    "model_versions", "retrain_runs", "drift_events", "audit_log",
)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    # Internal namespace for full-graph data used only by admin/R10. It is not a
    # real bank, is never marked loaded, and cannot have an analyst account.
    op.execute(
        "INSERT INTO tenants (tenant_id, bank_code, name, is_loaded) "
        "VALUES (-1, -1, 'Pooled', false) ON CONFLICT (tenant_id) DO NOTHING"
    )

    # RLS is forced even for the table owner. Deploy the API with a separate
    # non-owner role; never grant that role BYPASSRLS.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenants_read ON tenants FOR SELECT "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
        "OR current_setting('app.user_role', true) = 'admin' "
        "OR (current_setting('app.user_role', true) = 'auth' AND current_user = 'ringshield_auth'))"
    )
    op.execute(
        "CREATE POLICY tenants_admin_manage ON tenants FOR ALL "
        "USING (current_setting('app.user_role', true) = 'admin') "
        "WITH CHECK (current_setting('app.user_role', true) = 'admin')"
    )
    op.execute(
        "CREATE POLICY tenants_loader_read ON tenants FOR SELECT "
        "USING (current_user = 'ringshield_loader')"
    )

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_read ON {table} FOR SELECT "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
            "OR current_setting('app.user_role', true) = 'admin' "
            "OR current_user = 'ringshield_loader')"
        )

    # Contract ingestion uses its own restricted DB login, not the web/API login.
    # Its role must have table grants but must not own tables or BYPASSRLS.
    for table in ("accounts", "transactions", "rings", "explanations", "model_versions", "retrain_runs", "drift_events"):
        op.execute(
            f"CREATE POLICY {table}_loader_write ON {table} FOR INSERT "
            "WITH CHECK (current_user = 'ringshield_loader')"
        )
    for table in ("accounts", "transactions", "rings", "explanations", "model_versions", "retrain_runs", "drift_events"):
        op.execute(
            f"CREATE POLICY {table}_loader_update ON {table} FOR UPDATE "
            "USING (current_user = 'ringshield_loader') "
            "WITH CHECK (current_user = 'ringshield_loader')"
        )

    op.execute(
        "CREATE POLICY users_admin_manage ON users FOR ALL "
        "USING (current_setting('app.user_role', true) = 'admin') "
        "WITH CHECK (current_setting('app.user_role', true) = 'admin')"
    )
    op.execute(
        "CREATE POLICY users_auth_lookup ON users FOR SELECT "
        "USING (current_setting('app.user_role', true) = 'auth' AND current_user = 'ringshield_auth')"
    )
    op.execute(
        "CREATE POLICY model_versions_shared_read ON model_versions FOR SELECT "
        "USING (tenant_id IS NULL AND current_setting('app.user_role', true) IN ('analyst', 'supervisor'))"
    )
    op.execute(
        "CREATE POLICY rings_tenant_status_update ON rings FOR UPDATE "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
        "AND current_setting('app.user_role', true) IN ('analyst', 'supervisor')) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
        "AND current_setting('app.user_role', true) IN ('analyst', 'supervisor'))"
    )
    op.execute(
        "CREATE POLICY explanations_tenant_cache ON explanations FOR INSERT "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
        "AND current_setting('app.user_role', true) IN ('analyst', 'supervisor'))"
    )
    op.execute(
        "CREATE POLICY explanations_tenant_refresh ON explanations FOR UPDATE "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
        "AND current_setting('app.user_role', true) IN ('analyst', 'supervisor')) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
        "AND current_setting('app.user_role', true) IN ('analyst', 'supervisor'))"
    )
    op.execute(
        "CREATE POLICY verdicts_tenant_insert ON verdicts FOR INSERT "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
        "AND current_setting('app.user_role', true) IN ('analyst', 'supervisor') "
        "AND is_simulated IS FALSE)"
    )
    op.execute(
        "CREATE POLICY verdicts_simulator_insert ON verdicts FOR INSERT "
        "WITH CHECK (current_user = 'ringshield_simulator' AND is_simulated IS TRUE)"
    )
    op.execute(
        "CREATE POLICY retrain_runs_supervisor_insert ON retrain_runs FOR INSERT "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
        "AND current_setting('app.user_role', true) = 'supervisor')"
    )
    op.execute(
        "CREATE POLICY retrain_runs_supervisor_update ON retrain_runs FOR UPDATE "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
        "AND current_setting('app.user_role', true) = 'supervisor') "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
        "AND current_setting('app.user_role', true) = 'supervisor')"
    )
    op.execute(
        "CREATE POLICY drift_events_supervisor_update ON drift_events FOR UPDATE "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
        "AND current_setting('app.user_role', true) = 'supervisor') "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
        "AND current_setting('app.user_role', true) = 'supervisor')"
    )
    op.execute(
        "CREATE POLICY audit_tenant_insert ON audit_log FOR INSERT "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint "
        "OR current_setting('app.user_role', true) = 'admin' "
        "OR current_user = 'ringshield_loader')"
    )
    op.execute(
        "CREATE POLICY audit_global_insert ON audit_log FOR INSERT "
        "WITH CHECK (tenant_id IS NULL AND current_setting('app.user_role', true) = 'admin')"
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
