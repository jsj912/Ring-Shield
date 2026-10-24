"""Let the simulator read back the two columns its verdict insert returns."""

from alembic import op

revision = "0010_simulator_verdict_returning"
down_revision = "0009_explanation_revisions_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The ORM inserts with RETURNING verdict_id, created_at, which needs SELECT on
    # those columns. Row visibility stays with verdicts_tenant_read (tenant context).
    op.execute("GRANT SELECT (verdict_id, created_at) ON verdicts TO ringshield_simulator")


def downgrade() -> None:
    op.execute("REVOKE SELECT (verdict_id, created_at) ON verdicts FROM ringshield_simulator")
