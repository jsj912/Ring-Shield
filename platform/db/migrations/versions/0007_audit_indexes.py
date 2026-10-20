"""Add audit provenance and the missing Section 4 lookup indexes."""

from alembic import op
import sqlalchemy as sa

revision = "0007_audit_indexes"
down_revision = "0006_explanation_fx_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("actor", sa.String(length=80), nullable=True))
    op.add_column("audit_log", sa.Column("request_id", sa.String(length=36), nullable=True))
    # FORCE RLS also applies to the migration table owner. Permit only this
    # transactional backfill under the explicit migration role, then remove it.
    op.execute("CREATE POLICY audit_log_migration_backfill ON audit_log FOR UPDATE USING (current_user = 'ringshield_owner') WITH CHECK (current_user = 'ringshield_owner')")
    op.execute("UPDATE audit_log SET actor = CASE WHEN user_id IS NULL THEN 'legacy:unknown' ELSE 'user:' || user_id::text END WHERE actor IS NULL")
    op.execute("DROP POLICY audit_log_migration_backfill ON audit_log")
    op.alter_column("audit_log", "actor", nullable=False)

    # Match the exact descending confidence order in Section 4.
    op.drop_index("ix_rings_tenant_status_conf", table_name="rings")
    op.execute("CREATE INDEX ix_rings_tenant_status_conf ON rings (tenant_id, status, confidence DESC)")
    op.execute("CREATE INDEX ix_verdicts_tenant_ring_created ON verdicts (tenant_id, ring_id, created_at DESC)")

    # Audit reads are tenant scoped (administrators may inspect all tenants).
    op.execute("DROP POLICY audit_log_tenant_read ON audit_log")
    op.execute("""
        CREATE POLICY audit_log_tenant_read ON audit_log FOR SELECT
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
               OR current_setting('app.user_role', true) = 'admin')
    """)
    op.execute("DROP POLICY audit_tenant_insert ON audit_log")
    op.execute("DROP POLICY audit_global_insert ON audit_log")
    op.execute("""
        CREATE POLICY audit_tenant_insert ON audit_log FOR INSERT
        WITH CHECK (
          tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
          AND current_setting('app.user_role', true) IN ('analyst', 'supervisor', 'admin', 'loader')
          OR tenant_id IS NULL AND current_setting('app.user_role', true) = 'admin'
          OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
             AND current_user = 'ringshield_simulator'
             AND current_setting('app.user_role', true) = 'analyst'
        )
    """)

    # No application role or PUBLIC may mutate/delete audit records.
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC, ringshield_api, ringshield_loader, ringshield_simulator, ringshield_auth")
    op.execute("GRANT INSERT ON audit_log TO ringshield_api, ringshield_loader")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE audit_log_log_id_seq TO ringshield_api, ringshield_loader")


def downgrade() -> None:
    op.execute("REVOKE USAGE, SELECT ON SEQUENCE audit_log_log_id_seq FROM ringshield_api, ringshield_loader")
    op.execute("REVOKE INSERT ON audit_log FROM ringshield_api, ringshield_loader")
    op.execute("DROP POLICY audit_log_tenant_read ON audit_log")
    op.execute("""
        CREATE POLICY audit_log_tenant_read ON audit_log FOR SELECT
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
               OR current_setting('app.user_role', true) = 'admin'
               OR current_user = 'ringshield_loader')
    """)
    op.execute("DROP POLICY audit_tenant_insert ON audit_log")
    op.execute("DROP POLICY audit_global_insert ON audit_log")
    op.execute("""
        CREATE POLICY audit_tenant_insert ON audit_log FOR INSERT
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
                    OR current_setting('app.user_role', true) = 'admin'
                    OR current_user = 'ringshield_loader')
    """)
    op.execute("""
        CREATE POLICY audit_global_insert ON audit_log FOR INSERT
        WITH CHECK (tenant_id IS NULL AND current_setting('app.user_role', true) = 'admin')
    """)
    op.drop_index("ix_verdicts_tenant_ring_created", table_name="verdicts")
    op.drop_index("ix_rings_tenant_status_conf", table_name="rings")
    op.create_index("ix_rings_tenant_status_conf", "rings", ["tenant_id", "status", "confidence"])
    op.drop_column("audit_log", "request_id")
    op.drop_column("audit_log", "actor")
