"""Provision tenant-scoped access for simulated analyst verdicts."""

from alembic import op

revision = "0004_simulator_access"
down_revision = "0003_edge_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tighten the existing simulator policy: role and is_simulated alone are not
    # sufficient. The write must match both the tenant context and analyst role.
    op.execute("DROP POLICY verdicts_simulator_insert ON verdicts")
    op.execute("""
        CREATE POLICY verdicts_simulator_insert ON verdicts FOR INSERT
        WITH CHECK (
            current_user = 'ringshield_simulator'
            AND is_simulated IS TRUE
            AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::bigint
            AND current_setting('app.user_role', true) = 'analyst'
        )
    """)
    op.execute("GRANT SELECT ON rings, transactions TO ringshield_simulator")
    op.execute("GRANT SELECT (user_id, tenant_id, email, role, disabled) ON users TO ringshield_simulator")
    op.execute("GRANT UPDATE (status) ON rings TO ringshield_simulator")
    op.execute("GRANT INSERT ON verdicts TO ringshield_simulator")
    op.execute("GRANT INSERT ON audit_log TO ringshield_simulator")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE verdicts_verdict_id_seq, audit_log_log_id_seq TO ringshield_simulator")


def downgrade() -> None:
    # Keep the safer policy on downgrade; do not reintroduce its formerly broad
    # cross-tenant form. Privileges are revoked, leaving simulator disabled.
    op.execute("REVOKE USAGE, SELECT ON SEQUENCE verdicts_verdict_id_seq, audit_log_log_id_seq FROM ringshield_simulator")
    op.execute("REVOKE INSERT ON audit_log FROM ringshield_simulator")
    op.execute("REVOKE INSERT ON verdicts FROM ringshield_simulator")
    op.execute("REVOKE UPDATE (status) ON rings FROM ringshield_simulator")
    op.execute("REVOKE SELECT (user_id, tenant_id, email, role, disabled) ON users FROM ringshield_simulator")
    op.execute("REVOKE SELECT ON rings, transactions FROM ringshield_simulator")
