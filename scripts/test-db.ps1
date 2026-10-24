#!/usr/bin/env pwsh
[CmdletBinding()]
param(
    [int]$PostgresTimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot 'docker-compose.test.yml'
$python = (Get-Command python -ErrorAction Stop).Source
Push-Location $repoRoot

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $File $($Arguments -join ' ')"
    }
}

try {
    Invoke-Checked $python @('-m', 'pip', 'install', '-r', 'requirements-dev.txt')
    Invoke-Checked 'docker' @('compose', '-f', $composeFile, 'up', '-d', 'postgres-test')
    $deadline = [DateTime]::UtcNow.AddSeconds($PostgresTimeoutSeconds)
    $ready = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        & docker compose -f $composeFile exec -T postgres-test pg_isready -U postgres -d ringshield *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        & docker compose -f $composeFile logs postgres-test
        throw "Postgres did not become ready within $PostgresTimeoutSeconds seconds (pg_isready in postgres-test failed)."
    }

    $env:RINGSHIELD_DATABASE_ADMIN_URL = 'postgresql+psycopg://postgres:ringshield-test-only@localhost:55432/ringshield'
    $env:RINGSHIELD_DATABASE_ADMIN_PSQL_URL = 'postgresql://postgres:ringshield-test-only@localhost:55432/ringshield'
    $env:RINGSHIELD_TEST_ADMIN_URL = $env:RINGSHIELD_DATABASE_ADMIN_URL
    $env:RINGSHIELD_MIGRATION_DATABASE_URL = $env:RINGSHIELD_DATABASE_ADMIN_URL
    $env:RINGSHIELD_DATABASE_URL = 'postgresql+psycopg://ringshield_test_app:test-app-only@localhost:55432/ringshield?options=-c%20role%3Dringshield_api'
    $env:RINGSHIELD_AUTH_DATABASE_URL = 'postgresql+psycopg://ringshield_test_auth:test-auth-only@localhost:55432/ringshield?options=-c%20role%3Dringshield_auth'
    $env:RINGSHIELD_LOADER_DATABASE_URL = 'postgresql+psycopg://ringshield_test_loader:test-loader-only@localhost:55432/ringshield?options=-c%20role%3Dringshield_loader'
    $env:RINGSHIELD_JWT_SECRET = 'ringshield-test-secret-that-is-long-enough'
    # Test-only fixed anchor for deterministic synthetic fixtures; never use as a demo origin.
    # Test-only fixed anchor for deterministic synthetic fixtures; never use as a demo origin.
    $env:RINGSHIELD_TIME_ORIGIN_UTC = '2020-01-01T00:00:00+00:00'
    $env:RINGSHIELD_PLATFORM_CONFIG = 'platform/tests/isolation/config.test.yaml'

    # Bootstrap the schema and owner role, then run the remaining migrations as
    # a restricted member that SET ROLEs to the non-login owner role.
    Invoke-Checked $python @('-m', 'alembic', '-c', 'platform/alembic.ini', 'upgrade', '0002_role_ownership_force_rls')
    Invoke-Checked 'docker' @('compose', '-f', $composeFile, 'run', '--rm', 'test-runner', 'psql', 'postgresql://postgres:ringshield-test-only@postgres-test:5432/ringshield', '-v', 'ON_ERROR_STOP=1', '-f', 'platform/tests/isolation/provision_migration_role.sql')
    $env:RINGSHIELD_MIGRATION_DATABASE_URL = 'postgresql+psycopg://ringshield_test_migrator:test-migrator-only@localhost:55432/ringshield?options=-c%20role%3Dringshield_owner'
    Invoke-Checked $python @('-m', 'alembic', '-c', 'platform/alembic.ini', 'upgrade', 'head')

    Invoke-Checked 'docker' @('compose', '-f', $composeFile, 'run', '--rm', 'test-runner', 'psql', 'postgresql://postgres:ringshield-test-only@postgres-test:5432/ringshield', '-v', 'ON_ERROR_STOP=1', '-f', 'platform/db/roles.sql')
    Invoke-Checked 'docker' @('compose', '-f', $composeFile, 'run', '--rm', 'test-runner', 'psql', 'postgresql://postgres:ringshield-test-only@postgres-test:5432/ringshield', '-v', 'ON_ERROR_STOP=1', '-f', 'platform/tests/isolation/provision_test_roles.sql')

    $fixtureDir = Join-Path $env:TEMP 'ringshield-platform-fixture'
    $env:RINGSHIELD_TEST_FIXTURE_DIR = $fixtureDir
    Invoke-Checked $python @('platform/jobs/make_demo_fixture.py', '--output-dir', $fixtureDir)
    Invoke-Checked $python @('platform/tests/isolation/attach_fixture_logs.py', $fixtureDir)
    Invoke-Checked $python @('platform/jobs/seed_tenants.py', '--account-map', (Join-Path $fixtureDir 'account_bank.csv'), '--loaded-bank', '210', '--loaded-bank', '220')
    Invoke-Checked $python @('platform/jobs/load_contract.py', '--scored-edges', (Join-Path $fixtureDir 'scored_edges.parquet'), '--rings', (Join-Path $fixtureDir 'rings.parquet'), '--scope', 'tenant')
    Invoke-Checked $python @('platform/tests/isolation/seed_rls_fixture.py')

    $testOutput = & $python -m pytest platform/tests -rA 2>&1
    $pytestExitCode = $LASTEXITCODE
    $testOutput | ForEach-Object { Write-Host $_ }
    $outputText = $testOutput -join "`n"
    $passed = 0
    $rlsExecuted = 0
    if ($outputText -match '(?m)(\d+) passed') { $passed = [int]$Matches[1] }
    if ($outputText -match '(?m)RLS_POSTGRES_TESTS_EXECUTED=(\d+)') { $rlsExecuted = [int]$Matches[1] }
    Write-Host "Platform test summary: total passed=$passed; RLS tests executed against PostgreSQL=$rlsExecuted"
    if ($pytestExitCode -ne 0) { exit $pytestExitCode }
    if ($rlsExecuted -eq 0) { throw 'No RLS tests executed against PostgreSQL; refusing a false-green result.' }
}
finally {
    & docker compose -f $composeFile down --volumes --remove-orphans
    Pop-Location
}
