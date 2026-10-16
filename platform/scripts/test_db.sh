#!/bin/sh
set -eu

python -m alembic -c platform/alembic.ini upgrade 0002_role_ownership_force_rls
psql "$RINGSHIELD_DATABASE_ADMIN_PSQL_URL" -v ON_ERROR_STOP=1 \
  -f platform/tests/isolation/provision_migration_role.sql
RINGSHIELD_MIGRATION_DATABASE_URL='postgresql+psycopg://ringshield_test_migrator:test-migrator-only@postgres-test:5432/ringshield?options=-c%20role%3Dringshield_owner' \
  python -m alembic -c platform/alembic.ini upgrade head
psql "$RINGSHIELD_DATABASE_ADMIN_PSQL_URL" -v ON_ERROR_STOP=1 -f platform/db/roles.sql
psql "$RINGSHIELD_DATABASE_ADMIN_PSQL_URL" -v ON_ERROR_STOP=1 \
  -f platform/tests/isolation/provision_test_roles.sql

fixture_dir=/tmp/ringshield-platform-fixture
export RINGSHIELD_TEST_FIXTURE_DIR="$fixture_dir"
python platform/jobs/make_demo_fixture.py --output-dir "$fixture_dir"
python platform/tests/isolation/attach_fixture_logs.py "$fixture_dir"
python platform/jobs/seed_tenants.py \
  --account-map "$fixture_dir/account_bank.csv" \
  --loaded-bank 210 --loaded-bank 220
python platform/jobs/load_contract.py \
  --scored-edges "$fixture_dir/scored_edges.parquet" \
  --rings "$fixture_dir/rings.parquet" --scope tenant
python platform/tests/isolation/seed_rls_fixture.py

set +e
python -m pytest platform/tests -rA > /tmp/ringshield-platform-pytest.log 2>&1
pytest_status=$?
set -e
cat /tmp/ringshield-platform-pytest.log
passed=$(sed -nE 's/.*([0-9]+) passed.*/\1/p' /tmp/ringshield-platform-pytest.log | tail -n 1)
rls_count=$(sed -nE 's/.*RLS_POSTGRES_TESTS_EXECUTED=([0-9]+).*/\1/p' /tmp/ringshield-platform-pytest.log | tail -n 1)
passed=${passed:-0}
rls_count=${rls_count:-0}
echo "Platform test summary: total passed=$passed; RLS tests executed against PostgreSQL=$rls_count"
test "$pytest_status" -eq 0
test "$rls_count" -gt 0
