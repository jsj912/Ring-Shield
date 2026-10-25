#!/usr/bin/env pwsh
<#
.SYNOPSIS
    The five-seed R11 registered on 2026-10-25 (docs/R11.md): bank 1, detector seeds 1-5, accuracy 0.90 and 0.70.
.DESCRIPTION
    For each detector seed s the platform config is platform/out/r11/config_seed<s>.yaml
    (python -m experiments.r11_seed_config). For each (seed, accuracy) the demo database is rebuilt and
    bank 1 reloaded with seed s's rings and explanations, so every run starts from the same baseline,
    then platform/experiments/r11_gated_retrain.py runs 12 cycles with one gated retrain.
    Inputs that must exist for every seed:
      data/platform_tenant_runs/r11_seed<s>/T1/      (build_tenant_rings.py, config_seed<s>_build_T1.yaml)
      <ExplanationsDir>/explanations_1_<s>.parquet   (python -m explainability.tenant --bank 1, seed s)
    Uses the demo database on 127.0.0.1:55433 and its test logins; never point it at real data.
    Outputs: results/platform/r11/five_seeds/seed<s>/accuracy_<a>/ (cycles.md, models.json, run.json).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PlatformPython,
    [int[]]$Seeds = @(1, 2, 3, 4, 5),
    [double[]]$Accuracy = @(0.90, 0.70),
    [int]$Tenant = 1,
    [string]$ExplanationsDir = 'platform/out/r11/xai'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$python = (Resolve-Path -LiteralPath $PlatformPython).Path
$env:PATH = "$(Split-Path -Parent $python);$env:PATH"
$db = '127.0.0.1:' + $(if ($env:RINGSHIELD_DEMO_POSTGRES_PORT) { $env:RINGSHIELD_DEMO_POSTGRES_PORT } else { '55433' })

function Invoke-Demo([string[]]$Arguments) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run-demo.ps1') @Arguments
    if ($LASTEXITCODE -ne 0) { throw "run-demo.ps1 $($Arguments -join ' ') failed with exit code $LASTEXITCODE." }
}

$total = [Diagnostics.Stopwatch]::StartNew()
foreach ($s in $Seeds) {
    Push-Location (Join-Path $RepoRoot 'platform')
    try {
        & $python -m experiments.r11_seed_config --seed $s | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "seed config $s failed." }
    } finally { Pop-Location }
    $config = "platform/out/r11/config_seed$s.yaml"
    $runs = "data/platform_tenant_runs/r11_seed$s/T$Tenant"
    foreach ($a in $Accuracy) {
        Write-Host "== R11 seed $s accuracy ${a}: fresh demo database with bank $Tenant"
        Invoke-Demo @('-Down', '-DropVolume')
        Invoke-Demo @('-Tenants', "$Tenant", '-TimeOriginUtc', '2022-08-31T23:59:50Z',
            '-RingsDir', $runs, '-EdgeIdsDir', $runs,
            '-ScoredEdges', "contract/out/scored_edges_gine_causal_$s.parquet",
            '-ExplanationsDir', $ExplanationsDir, '-PlatformConfig', $config)

        $env:RINGSHIELD_DATABASE_URL = "postgresql+psycopg://ringshield_test_app:test-app-only@$db/ringshield?options=-c%20role%3Dringshield_api"
        $env:RINGSHIELD_LOADER_DATABASE_URL = "postgresql+psycopg://ringshield_test_loader:test-loader-only@$db/ringshield?options=-c%20role%3Dringshield_loader"
        $env:RINGSHIELD_SIMULATOR_DATABASE_URL = "postgresql+psycopg://ringshield_test_simulator:test-simulator-only@$db/ringshield?options=-c%20role%3Dringshield_simulator"
        $env:RINGSHIELD_PLATFORM_CONFIG = Join-Path $RepoRoot $config
        $env:RINGSHIELD_TIME_ORIGIN_UTC = '2022-08-31T23:59:50Z'
        $env:PYTHON_DOTENV_DISABLED = '1'
        Push-Location (Join-Path $RepoRoot 'platform')
        try {
            & $python -m experiments.r11_gated_retrain --tenant-id $Tenant --accuracy ('{0:0.00}' -f $a) `
                --out-root (Join-Path $RepoRoot "results/platform/r11/five_seeds/seed$s")
            if ($LASTEXITCODE -ne 0) { throw "R11 seed $s accuracy $a failed with exit code $LASTEXITCODE." }
        } finally {
            Pop-Location
        }
    }
}
Invoke-Demo @('-Down')
Write-Host ("R11 five seeds done in {0:N0} s: results/platform/r11/five_seeds/" -f $total.Elapsed.TotalSeconds)
