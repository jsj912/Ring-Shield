"""Establish a non-login schema owner and force RLS on every tenant table."""

from alembic import op

revision = "0002_role_ownership_force_rls"
down_revision = "0001_platform_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ringshield_owner') THEN
                CREATE ROLE ringshield_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ringshield_api') THEN
                CREATE ROLE ringshield_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ringshield_loader') THEN
                CREATE ROLE ringshield_loader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ringshield_simulator') THEN
                CREATE ROLE ringshield_simulator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            END IF;
        END $$;
    """)
    op.execute("GRANT USAGE, CREATE ON SCHEMA public TO ringshield_owner")
    # Force the owner role to remain subject to RLS during ordinary SQL use.
    op.execute("""
        DO $$ DECLARE t record; BEGIN
            FOR t IN SELECT schemaname, tablename FROM pg_tables
                     WHERE schemaname = 'public'
            LOOP
                EXECUTE format('ALTER TABLE %I.%I OWNER TO ringshield_owner', t.schemaname, t.tablename);
            END LOOP;
            FOR t IN SELECT sequence_schema, sequence_name
                     FROM information_schema.sequences WHERE sequence_schema = 'public'
            LOOP
                EXECUTE format('ALTER SEQUENCE %I.%I OWNER TO ringshield_owner',
                               t.sequence_schema, t.sequence_name);
            END LOOP;
        END $$;
    """)
    # Revision 0003 grants this role access to its new score table.
    op.execute("GRANT USAGE ON SCHEMA public TO ringshield_loader")
    op.execute("""
        DO $$ DECLARE t record; BEGIN
            FOR t IN
                SELECT DISTINCT table_schema, table_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND column_name = 'tenant_id'
            LOOP
                EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', t.table_schema, t.table_name);
                EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY', t.table_schema, t.table_name);
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    # RLS and owner hardening are security invariants and are intentionally not
    # undone by a downgrade. Role deletion can break external deployments.
    pass
