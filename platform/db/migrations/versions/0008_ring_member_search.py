"""Index tenant ring membership for exact account search."""

from alembic import op

revision = "0008_ring_member_search"
down_revision = "0007_audit_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_rings_member_accounts_gin ON rings USING GIN (member_accounts)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_rings_member_accounts_gin")
