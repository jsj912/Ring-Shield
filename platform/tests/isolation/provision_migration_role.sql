CREATE ROLE ringshield_test_migrator LOGIN PASSWORD 'test-migrator-only'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
GRANT ringshield_owner TO ringshield_test_migrator;
