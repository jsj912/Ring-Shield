"""Make daily drift event writes safe under concurrent monitor runs."""

from alembic import op

revision = "0005_drift_event_dedupe"
down_revision = "0004_simulator_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_drift_events_tenant_monitor_window_end",
        "drift_events",
        ["tenant_id", "monitor", "window_end"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_drift_events_tenant_monitor_window_end", "drift_events", type_="unique"
    )
