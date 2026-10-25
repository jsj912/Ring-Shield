"""A supervisor's note on a drift event's acted-on flag (FR-D81): why it was marked reviewed or not."""

import sqlalchemy as sa
from alembic import op

revision = "0012_drift_acted_on_note"
down_revision = "0011_model_version_retrain_run"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("drift_events", sa.Column("acted_on_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("drift_events", "acted_on_note")
