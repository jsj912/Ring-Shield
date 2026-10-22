"""Add immutable explanation revisions and tenant-scoped regeneration jobs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_explanation_revisions_jobs"
down_revision = "0008_ring_member_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL assigns the constant default to existing rows without an UPDATE.
    op.add_column("explanations", sa.Column(
        "revision", sa.Integer(), nullable=False, server_default=sa.text("1")))
    op.alter_column("explanations", "created_at",
                    existing_type=sa.DateTime(timezone=True),
                    server_default=sa.text("clock_timestamp()"))
    op.drop_constraint("explanations_pkey", "explanations", type_="primary")
    op.create_primary_key(
        "explanations_pkey", "explanations",
        ["tenant_id", "ring_id", "explainer_version", "revision"],
    )
    op.create_table(
        "explanation_jobs",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("ring_id", sa.String(length=180), nullable=False),
        sa.Column("verdict_id", sa.BigInteger(), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("excluded_members", postgresql.ARRAY(sa.BigInteger()),
                  server_default=sa.text("'{}'::bigint[]"), nullable=False),
        sa.Column("excluded_edges", postgresql.ARRAY(sa.BigInteger()),
                  server_default=sa.text("'{}'::bigint[]"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_revision", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')",
                           name="ck_explanation_jobs_status"),
        sa.UniqueConstraint("tenant_id", "verdict_id", name="uq_explanation_jobs_tenant_verdict"),
        sa.ForeignKeyConstraint(["tenant_id", "ring_id"], ["rings.tenant_id", "rings.ring_id"],
                                name="fk_explanation_jobs_tenant_ring", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "requested_by"],
                                ["users.tenant_id", "users.user_id"],
                                name="fk_explanation_jobs_tenant_user"),
        sa.PrimaryKeyConstraint("job_id", name="pk_explanation_jobs"),
    )
    op.create_index("ix_explanation_jobs_status_created", "explanation_jobs",
                    ["status", "created_at"], postgresql_where=sa.text("status = 'queued'"))
    op.create_index("ix_explanation_jobs_tenant_ring", "explanation_jobs", ["tenant_id", "ring_id"])
    op.execute("ALTER TABLE explanation_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE explanation_jobs FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY explanation_jobs_tenant_select ON explanation_jobs FOR SELECT
        USING (
          (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
           AND current_user IN ('ringshield_api', 'ringshield_loader'))
          OR (current_setting('app.user_role', true) = 'admin'
              AND current_user = 'ringshield_api')
        )
    """)
    op.execute("""
        CREATE POLICY explanation_jobs_api_insert ON explanation_jobs FOR INSERT
        WITH CHECK (
          tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
          AND current_user = 'ringshield_api'
          AND current_setting('app.user_role', true) IN ('analyst', 'supervisor')
        )
    """)
    op.execute("""
        CREATE POLICY explanation_jobs_loader_update ON explanation_jobs FOR UPDATE
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
               AND current_user = 'ringshield_loader')
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
                    AND current_user = 'ringshield_loader')
    """)
    op.execute("REVOKE ALL ON explanation_jobs FROM PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ringshield_api') THEN
                EXECUTE 'GRANT SELECT, INSERT ON explanation_jobs TO ringshield_api';
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ringshield_loader') THEN
                EXECUTE 'GRANT SELECT, UPDATE ON explanation_jobs TO ringshield_loader';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS explanation_jobs")
    op.execute("ALTER TABLE explanations DROP CONSTRAINT IF EXISTS explanations_pkey")
    op.execute("ALTER TABLE explanations DROP COLUMN IF EXISTS revision")
    op.alter_column("explanations", "created_at",
                    existing_type=sa.DateTime(timezone=True),
                    server_default=sa.text("now()"))
    op.create_primary_key("explanations_pkey", "explanations",
                          ["tenant_id", "ring_id", "explainer_version"])
