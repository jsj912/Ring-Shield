#!/usr/bin/env pwsh
<#
.SYNOPSIS
    R11 as amended in docs/R11.md: bank 1, 12 four-hour cycles over days 8-9, one gated retrain.
.DESCRIPTION
    For each accuracy condition the demo database is rebuilt and bank 1 reloaded, so both runs
    start from the same baseline (the run writes simulated verdicts and model history). Bank 1's
    rings and explanations must already exist:
      data/platform_tenant_runs/r11_visible_seed1/T1/   (build_tenant_rings.py on its own scores)
      results/xai/tenant/explanations_1_1.parquet       (python -m explainability.tenant --bank 1)
    Uses the demo database on 127.0.0.1:55433 and its test logins; never point it at real data.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PlatformPython,
    [double[]]$Accuracy = @(0.90, 0.70),
    [int]$Tenant = 1
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$python = (Resolve-Path -LiteralPath $PlatformPython).Path
$env:PATH = "$(Split-Path -Parent $python);$env:PATH"
$runs = "data/platform_tenant_runs/r11_visible_seed1/T$Tenant"
$db = '127.0.0.1:' + $(if ($env:RINGSHIELD_DEMO_POSTGRES_PORT) { $env:RINGSHIELD_DEMO_POSTGRES_PORT } else { '55433' })

function Invoke-Demo([string[]]$Arguments) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run-demo.ps1') @Arguments
    if ($LASTEXITCODE -ne 0) { throw "run-demo.ps1 $($Arguments -join ' ') failed with exit code $LASTEXITCODE." }
}

foreach ($a in $Accuracy) {
    Write-Host "== R11 accuracy ${a}: fresh demo database with bank $Tenant"
    Invoke-Demo @('-Down', '-DropVolume')
    Invoke-Demo @('-Tenants', "$Tenant", '-TimeOriginUtc', '2022-08-31T23:59:50Z',
        '-RingsDir', $runs, '-EdgeIdsDir', $runs,
        '-ScoredEdges', 'contract/out/scored_edges_gine_causal_1.parquet',
        '-ExplanationsDir', 'results/xai/tenant')

    $env:RINGSHIELD_DATABASE_URL = "postgresql+psycopg://ringshield_test_app:test-app-only@$db/ringshield?options=-c%20role%3Dringshield_api"
    $env:RINGSHIELD_LOADER_DATABASE_URL = "postgresql+psycopg://ringshield_test_loader:test-loader-only@$db/ringshield?options=-c%20role%3Dringshield_loader"
    $env:RINGSHIELD_SIMULATOR_DATABASE_URL = "postgresql+psycopg://ringshield_test_simulator:test-simulator-only@$db/ringshield?options=-c%20role%3Dringshield_simulator"
    $env:RINGSHIELD_PLATFORM_CONFIG = 'platform/config.yaml'
    $env:RINGSHIELD_TIME_ORIGIN_UTC = '2022-08-31T23:59:50Z'
    $env:PYTHON_DOTENV_DISABLED = '1'
    Push-Location (Join-Path $RepoRoot 'platform')
    try {
        & $python -m experiments.r11_gated_retrain --tenant-id $Tenant --accuracy ('{0:0.00}' -f $a)
        if ($LASTEXITCODE -ne 0) { throw "R11 accuracy $a failed with exit code $LASTEXITCODE." }
    } finally {
        Pop-Location
    }
}
Invoke-Demo @('-Down')
Write-Host 'R11 done: results/platform/r11/accuracy_<a>/cycles.md'
