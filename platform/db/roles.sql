-- Run as the database owner after Alembic has created the platform tables.
-- Provision login roles separately and grant membership to the appropriate
-- no-login role. Neither application role may own tables or BYPASSRLS.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ringshield_api') THEN
        CREATE ROLE ringshield_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ringshield_loader') THEN
        CREATE ROLE ringshield_loader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ringshield_auth') THEN
        CREATE ROLE ringshield_auth NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ringshield_simulator') THEN
        CREATE ROLE ringshield_simulator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO ringshield_api, ringshield_loader, ringshield_auth, ringshield_simulator;

GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO ringshield_api;
GRANT SELECT ON tenants TO ringshield_loader;
GRANT SELECT (user_id, tenant_id, email, role, created_at, disabled),
    INSERT (tenant_id, email, password_hash, role),
    UPDATE (tenant_id, email, password_hash, role, disabled) ON users TO ringshield_api;
GRANT SELECT ON accounts, transactions, edge_scores, rings, explanations, verdicts,
    model_versions, retrain_runs, drift_events, audit_log TO ringshield_api;
GRANT INSERT ON explanations, verdicts, retrain_runs, audit_log TO ringshield_api;
GRANT UPDATE ON rings, explanations, retrain_runs, drift_events TO ringshield_api;

GRANT SELECT, INSERT, UPDATE ON accounts, transactions, edge_scores, rings, explanations,
    model_versions, retrain_runs, drift_events TO ringshield_loader;
GRANT INSERT ON audit_log TO ringshield_loader;
GRANT SELECT (user_id, tenant_id, email, password_hash, role, created_at, disabled) ON users TO ringshield_auth;
GRANT SELECT ON tenants TO ringshield_auth;
GRANT INSERT ON verdicts TO ringshield_simulator;
GRANT SELECT ON rings, transactions TO ringshield_simulator;
GRANT SELECT (user_id, tenant_id, email, role, disabled) ON users TO ringshield_simulator;
GRANT UPDATE (status) ON rings TO ringshield_simulator;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ringshield_api, ringshield_loader, ringshield_simulator;

-- Create separate LOGIN roles outside this script, set their passwords from a
-- secret manager, then grant membership as appropriate:
--   CREATE ROLE ringshield_owner_login LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
--   GRANT ringshield_owner TO ringshield_owner_login;
--   GRANT ringshield_api TO ringshield_runtime_login;
--   GRANT ringshield_auth TO ringshield_auth_login;
--   GRANT ringshield_loader TO ringshield_loader_login;
--   GRANT ringshield_simulator TO ringshield_simulator_login;
-- Connect with SET ROLE to the granted role (for example options=-crole=ringshield_api).
