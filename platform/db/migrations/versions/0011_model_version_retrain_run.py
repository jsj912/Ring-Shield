"""Record which retrain run produced each model version, so a refused run can point to its
candidates and their gate reasons (the run itself only links a promoted version)."""

import sqlalchemy as sa
from alembic import op

revision = "0011_model_version_retrain_run"
down_revision = "0010_simulator_verdict_returning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_versions", sa.Column("retrain_run_id", sa.String(64), nullable=True))
    op.create_index("ix_model_versions_tenant_run", "model_versions", ["tenant_id", "retrain_run_id"])


def downgrade() -> None:
    op.drop_index("ix_model_versions_tenant_run", table_name="model_versions")
    op.drop_column("model_versions", "retrain_run_id")
