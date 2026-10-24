DO $$ BEGIN
    CREATE ROLE ringshield_test_migrator LOGIN PASSWORD 'test-migrator-only'
        NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
GRANT ringshield_owner TO ringshield_test_migrator;
