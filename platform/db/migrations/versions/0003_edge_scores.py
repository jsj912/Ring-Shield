"""Store detector scores separately by tenant, edge, model, and seed."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_edge_scores"
down_revision = "0002_role_ownership_force_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Scores lived on transactions in the initial schema. The durable, model-
    # specific representation below replaces those mutable cached columns.
    op.drop_column("transactions", "score_calibrated")
    op.drop_column("transactions", "is_seed")
    op.drop_column("transactions", "model_id")
    op.drop_column("transactions", "seed")
    op.create_table(
        "edge_scores",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("edge_id", sa.BigInteger(), nullable=False),
        sa.Column("model_id", sa.String(length=80), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("score_raw", sa.Float(), nullable=True),
        sa.Column("score_calibrated", sa.Float(), nullable=True),
        sa.Column("is_seed", sa.Boolean(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.PrimaryKeyConstraint("tenant_id", "edge_id", "model_id", "seed"),
    )
    op.create_index("ix_edge_scores_active", "edge_scores", ["tenant_id", "model_id", "seed", "edge_id"])
    op.execute("ALTER TABLE edge_scores ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE edge_scores FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY edge_scores_tenant_read ON edge_scores FOR SELECT
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
               OR current_setting('app.user_role', true) = 'admin'
               OR current_user = 'ringshield_loader')
    """)
    op.execute("""
        CREATE POLICY edge_scores_loader_insert ON edge_scores FOR INSERT
        WITH CHECK (current_user = 'ringshield_loader')
    """)
    op.execute("""
        CREATE POLICY edge_scores_loader_update ON edge_scores FOR UPDATE
        USING (current_user = 'ringshield_loader')
        WITH CHECK (current_user = 'ringshield_loader')
    """)
    op.execute("ALTER TABLE edge_scores OWNER TO ringshield_owner")
    op.execute("GRANT SELECT ON edge_scores TO ringshield_api")
    op.execute("GRANT SELECT, INSERT, UPDATE ON edge_scores TO ringshield_loader")


def downgrade() -> None:
    op.drop_table("edge_scores")
    op.add_column("transactions", sa.Column("seed", sa.Integer(), nullable=True))
    op.add_column("transactions", sa.Column("model_id", sa.String(length=80), nullable=True))
    op.add_column("transactions", sa.Column("is_seed", sa.Boolean(), nullable=True))
    op.add_column("transactions", sa.Column("score_calibrated", sa.Float(), nullable=True))
