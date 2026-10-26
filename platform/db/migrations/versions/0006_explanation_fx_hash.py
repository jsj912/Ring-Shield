"""Persist the FX table hash used by each L4 explanation."""

from alembic import op
import sqlalchemy as sa

revision = "0006_explanation_fx_hash"
down_revision = "0005_drift_event_dedupe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("explanations", sa.Column("fx_rates_sha256", sa.String(length=64), nullable=True))
    op.execute("""
        UPDATE explanations
        SET fx_rates_sha256 = provenance->>'fx_rates_sha256'
        WHERE provenance ? 'fx_rates_sha256'
    """)


def downgrade() -> None:
    op.drop_column("explanations", "fx_rates_sha256")
