"""Frozen initial tenant-scoped platform schema (revision 0001)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_platform_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These definitions are intentionally frozen. Do not import ORM metadata here:
    # later model additions belong in their own migration revisions.
    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("bank_code", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_loaded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.UniqueConstraint("bank_code"),
    )
    op.create_table(
        "users",
        sa.Column("user_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("disabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("role IN ('analyst', 'supervisor', 'admin')", name="ck_users_role"),
        sa.CheckConstraint("(role = 'admin' AND tenant_id IS NULL) OR (role IN ('analyst', 'supervisor') AND tenant_id IS NOT NULL)", name="ck_users_role_tenant"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_users_tenant_user"),
    )
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)
    op.create_table(
        "accounts",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("bank_code", sa.BigInteger(), nullable=False),
        sa.Column("first_seen", sa.BigInteger(), nullable=True),
        sa.Column("last_seen", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.PrimaryKeyConstraint("tenant_id", "account_id"),
    )
    op.create_index("ix_accounts_tenant_bank", "accounts", ["tenant_id", "bank_code"])
    op.create_table(
        "transactions",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("edge_id", sa.BigInteger(), nullable=False),
        sa.Column("from_id", sa.BigInteger(), nullable=False),
        sa.Column("to_id", sa.BigInteger(), nullable=False),
        sa.Column("from_bank", sa.BigInteger(), nullable=False),
        sa.Column("to_bank", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.Column("amount_sent", sa.Float(), nullable=True),
        sa.Column("amount_received", sa.Float(), nullable=True),
        sa.Column("currency_sent", sa.Integer(), nullable=True),
        sa.Column("currency_received", sa.Integer(), nullable=True),
        sa.Column("payment_format", sa.Integer(), nullable=True),
        sa.Column("score_calibrated", sa.Float(), nullable=True),
        sa.Column("is_seed", sa.Boolean(), nullable=True),
        sa.Column("model_id", sa.String(length=80), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.PrimaryKeyConstraint("tenant_id", "edge_id"),
    )
    op.create_index("ix_transactions_tenant_time", "transactions", ["tenant_id", "timestamp"])
    op.create_index("ix_transactions_tenant_from", "transactions", ["tenant_id", "from_id"])
    op.create_index("ix_transactions_tenant_to", "transactions", ["tenant_id", "to_id"])
    op.create_table(
        "rings",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("ring_id", sa.String(length=180), nullable=False),
        sa.Column("model_id", sa.String(length=80), nullable=False),
        sa.Column("aggregator_id", sa.String(length=40), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=12), server_default=sa.text("'tenant'"), nullable=False),
        sa.Column("member_accounts", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("member_edges", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("seed_edges", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("expanded_edges", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("conservation_closure", sa.Float(), nullable=True),
        sa.Column("topology_type", sa.String(length=32), nullable=False),
        sa.Column("topology_probs", postgresql.ARRAY(sa.Float(), dimensions=1), nullable=False),
        sa.Column("start_time", sa.BigInteger(), nullable=False),
        sa.Column("end_time", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'open'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.CheckConstraint("scope IN ('tenant', 'pooled')", name="ck_rings_scope"),
        sa.CheckConstraint("status IN ('open', 'confirmed', 'rejected', 'partial')", name="ck_rings_status"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.PrimaryKeyConstraint("tenant_id", "ring_id"),
    )
    op.create_index("ix_rings_tenant_status_conf", "rings", ["tenant_id", "status", "confidence"])
    op.create_index("ix_rings_tenant_start", "rings", ["tenant_id", "start_time"])
    op.create_table(
        "explanations",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("ring_id", sa.String(length=180), nullable=False),
        sa.Column("explainer_version", sa.String(length=80), nullable=False),
        sa.Column("edge_weights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("account_weights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("feature_weights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("evidence_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "ring_id"], ["rings.tenant_id", "rings.ring_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", "ring_id", "explainer_version"),
    )
    op.create_table(
        "verdicts",
        sa.Column("verdict_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("ring_id", sa.String(length=180), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("verdict", sa.String(length=12), nullable=False),
        sa.Column("corrected_members", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("corrected_edges", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("verdict IN ('confirm', 'reject', 'partial')", name="ck_verdicts_kind"),
        sa.ForeignKeyConstraint(["tenant_id", "ring_id"], ["rings.tenant_id", "rings.ring_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.user_id"]),
        sa.PrimaryKeyConstraint("verdict_id"),
    )
    op.create_index("ix_verdicts_tenant_created", "verdicts", ["tenant_id", "created_at"])
    op.create_table(
        "model_versions",
        sa.Column("model_version_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("component", sa.String(length=16), nullable=False),
        sa.Column("version_tag", sa.String(length=80), nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("train_label_count", sa.Integer(), nullable=False),
        sa.Column("holdout_ring_f1", sa.Float(), nullable=True),
        sa.Column("promoted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("gate_reason", sa.Text(), nullable=True),
        sa.Column("artifact_path", sa.Text(), nullable=True),
        sa.CheckConstraint("component IN ('expansion', 'affinity', 'typing', 'detector')", name="ck_model_versions_component"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.PrimaryKeyConstraint("model_version_id"),
        sa.UniqueConstraint("tenant_id", "model_version_id", name="uq_model_versions_tenant_version"),
    )
    op.create_index("uq_model_versions_promoted", "model_versions", ["tenant_id", "component"], unique=True, postgresql_where=sa.text("promoted IS TRUE"))
    op.create_index("ix_model_versions_tenant_component", "model_versions", ["tenant_id", "component", "trained_at"])
    op.create_table(
        "retrain_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("triggered_by", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("model_version_id", sa.BigInteger(), nullable=True),
        sa.Column("log_path", sa.Text(), nullable=True),
        sa.CheckConstraint("triggered_by IN ('schedule', 'supervisor')", name="ck_retrain_runs_trigger"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.ForeignKeyConstraint(["tenant_id", "model_version_id"], ["model_versions.tenant_id", "model_versions.model_version_id"]),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_retrain_runs_tenant_started", "retrain_runs", ["tenant_id", "started_at"])
    op.create_table(
        "drift_events",
        sa.Column("event_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("monitor", sa.String(length=32), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("statistic", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("acted_on", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("monitor IN ('adwin_score_mean', 'adwin_score_p99')", name="ck_drift_events_monitor"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_drift_events_tenant_detected", "drift_events", ["tenant_id", "detected_at"])
    op.create_table(
        "audit_log",
        sa.Column("log_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("object_type", sa.String(length=80), nullable=False),
        sa.Column("object_id", sa.String(length=180), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.PrimaryKeyConstraint("log_id"),
    )
    op.create_index("ix_audit_log_tenant_at", "audit_log", ["tenant_id", "at"])

    op.execute("INSERT INTO tenants (tenant_id, bank_code, name, is_loaded) VALUES (-1, -1, 'Pooled', false)")
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenants_read ON tenants FOR SELECT USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint OR current_setting('app.user_role', true) = 'admin' OR (current_setting('app.user_role', true) = 'auth' AND current_user = 'ringshield_auth'))")
    op.execute("CREATE POLICY tenants_admin_manage ON tenants FOR ALL USING (current_setting('app.user_role', true) = 'admin') WITH CHECK (current_setting('app.user_role', true) = 'admin')")
    op.execute("CREATE POLICY tenants_loader_read ON tenants FOR SELECT USING (current_user = 'ringshield_loader')")
    tenant_tables = ("users", "accounts", "transactions", "rings", "explanations", "verdicts", "model_versions", "retrain_runs", "drift_events", "audit_log")
    for table in tenant_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_tenant_read ON {table} FOR SELECT USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint OR current_setting('app.user_role', true) = 'admin' OR current_user = 'ringshield_loader')")
    for table in ("accounts", "transactions", "rings", "explanations", "model_versions", "retrain_runs", "drift_events"):
        op.execute(f"CREATE POLICY {table}_loader_write ON {table} FOR INSERT WITH CHECK (current_user = 'ringshield_loader')")
        op.execute(f"CREATE POLICY {table}_loader_update ON {table} FOR UPDATE USING (current_user = 'ringshield_loader') WITH CHECK (current_user = 'ringshield_loader')")
    op.execute("CREATE POLICY users_admin_manage ON users FOR ALL USING (current_setting('app.user_role', true) = 'admin') WITH CHECK (current_setting('app.user_role', true) = 'admin')")
    op.execute("CREATE POLICY users_auth_lookup ON users FOR SELECT USING (current_setting('app.user_role', true) = 'auth' AND current_user = 'ringshield_auth')")
    op.execute("CREATE POLICY model_versions_shared_read ON model_versions FOR SELECT USING (tenant_id IS NULL AND current_setting('app.user_role', true) IN ('analyst', 'supervisor'))")
    op.execute("CREATE POLICY rings_tenant_status_update ON rings FOR UPDATE USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint AND current_setting('app.user_role', true) IN ('analyst', 'supervisor')) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint AND current_setting('app.user_role', true) IN ('analyst', 'supervisor'))")
    op.execute("CREATE POLICY explanations_tenant_cache ON explanations FOR INSERT WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint AND current_setting('app.user_role', true) IN ('analyst', 'supervisor'))")
    op.execute("CREATE POLICY explanations_tenant_refresh ON explanations FOR UPDATE USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint AND current_setting('app.user_role', true) IN ('analyst', 'supervisor')) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint AND current_setting('app.user_role', true) IN ('analyst', 'supervisor'))")
    op.execute("CREATE POLICY verdicts_tenant_insert ON verdicts FOR INSERT WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint AND current_setting('app.user_role', true) IN ('analyst', 'supervisor') AND is_simulated IS FALSE)")
    op.execute("CREATE POLICY verdicts_simulator_insert ON verdicts FOR INSERT WITH CHECK (current_user = 'ringshield_simulator' AND is_simulated IS TRUE)")
    op.execute("CREATE POLICY retrain_runs_supervisor_insert ON retrain_runs FOR INSERT WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint AND current_setting('app.user_role', true) = 'supervisor')")
    op.execute("CREATE POLICY retrain_runs_supervisor_update ON retrain_runs FOR UPDATE USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint AND current_setting('app.user_role', true) = 'supervisor') WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint AND current_setting('app.user_role', true) = 'supervisor')")
    op.execute("CREATE POLICY drift_events_supervisor_update ON drift_events FOR UPDATE USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint AND current_setting('app.user_role', true) = 'supervisor') WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint AND current_setting('app.user_role', true) = 'supervisor')")
    op.execute("CREATE POLICY audit_tenant_insert ON audit_log FOR INSERT WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint OR current_setting('app.user_role', true) = 'admin' OR current_user = 'ringshield_loader')")
    op.execute("CREATE POLICY audit_global_insert ON audit_log FOR INSERT WITH CHECK (tenant_id IS NULL AND current_setting('app.user_role', true) = 'admin')")


def downgrade() -> None:
    for table in ("audit_log", "drift_events", "retrain_runs", "model_versions", "verdicts", "explanations", "rings", "transactions", "accounts", "users", "tenants"):
        op.drop_table(table)
