#!/usr/bin/env pwsh
<#
.SYNOPSIS
    One command for the RingShield demonstration: Postgres, migrations, seed-1 rings and
    explanations for banks 12 and 20, demo users, the API, and the React production build.
.DESCRIPTION
    Checks Python, Node/npm and Postgres (Docker) first and prints everything that is missing.
    Every run starts from an empty demo database (the previous demo volume is dropped), then
    calls scripts/run-demo.ps1 for Postgres, migrations, loading, users, the API and the worker
    supervisor, builds platform/frontend and serves the build with `vite preview`.
    The L4 regeneration service (python -m explainability.serve, Python from XAI_PYTHON or
    ..\venv-xai) runs on 127.0.0.1:8765 so that a partial verdict regenerates the narrative; it
    is given the same ring files the demo loads.

    Logins: an analyst at banks 12 and 20, a supervisor at bank 12, and an administrator.
    Stop everything with: .\scripts\run-demo.ps1 -Down

    -R11History adds R11's history to the supervisor's bank before the dashboard starts: twelve
    cycles of simulated verdicts and one gated retrain (platform/experiments/r11_gated_retrain.py,
    accuracy 0.90), as registered in docs/R11.md. Bank 12 holds too few rings for a retrain
    (l6.retrain.min_new_labels), so the history demo runs on bank 1, R11's bank; see the example.

    -FromProcessedData runs the whole chain from data/processed/: for each bank it first builds the
    bank's rings from its visible edges and explains them with L4 (scripts/e2e_demo.ps1
    -PrepareOnly, research Python .venv312), then loads those fresh files. Without it the demo
    loads the seed-1 rings and explanations already in -InputsDir.

    This is the one entry point. scripts/run-demo.ps1 and scripts/e2e_demo.ps1 are helpers it calls.
.EXAMPLE
    .\scripts\demo.ps1
.EXAMPLE
    .\scripts\demo.ps1 -FromProcessedData
.EXAMPLE
    .\scripts\demo.ps1 -Tenants 1 -SupervisorTenants 1 -InputsDir data/platform_tenant_runs/r11_seed1/T1 `
        -ExplanationsDir platform/out/r11/xai -R11History
#>
[CmdletBinding()]
param(
    [string]$InputsDir = 'data/platform_tenant_runs/gine_causal_seed1',
    [string]$ScoredEdges = 'contract/out/scored_edges_gine_causal_1.parquet',
    [string]$TimeOriginUtc = '2022-08-31T23:59:50Z',
    [string]$ExplanationsDir = '',
    [string]$PlatformConfig = '',
    [string[]]$Tenants = @('12', '20'),
    [string[]]$SupervisorTenants = @('12'),
    [int]$WebPort = 5173,
    [int]$L4Port = 8765,
    [switch]$R11History,
    [switch]$FromProcessedData
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $repoRoot 'platform/frontend'
$tenants = @($Tenants -split ',' | Where-Object { $_ })
$supervisorTenants = @($SupervisorTenants -split ',' | Where-Object { $_ })
if (-not $ExplanationsDir) { $ExplanationsDir = if ($FromProcessedData) { 'results/xai/tenant' } else { $InputsDir } }
$missing = [System.Collections.Generic.List[string]]::new()

function Test-Version {
    param([string]$Text, [version]$Minimum)
    $match = [regex]::Match($Text, '(\d+)\.(\d+)(?:\.(\d+))?')
    if (-not $match.Success) { return $false }
    return ([version]$match.Value) -ge $Minimum
}

# Python: PYTHON wins; else the platform venv next to the repo; else python on PATH (as run-demo.ps1).
$venvPython = Join-Path (Split-Path -Parent $repoRoot) 'venv-platform/Scripts/python.exe'
$python = if ($env:PYTHON) { $env:PYTHON } elseif (Test-Path -LiteralPath $venvPython) { $venvPython } else {
    (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $python) {
    $missing.Add('Python 3.11 or newer (not on PATH; or set PYTHON to its python.exe)')
} elseif (-not (Test-Version (& $python --version 2>&1 | Out-String) ([version]'3.11'))) {
    $missing.Add("Python 3.11 or newer ($python reports $((& $python --version 2>&1 | Out-String).Trim()))")
}

$node = Get-Command node -ErrorAction SilentlyContinue
$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $node) { $missing.Add('Node.js 18 or newer (node is not on PATH)') }
elseif (-not (Test-Version (& node --version) ([version]'18.0'))) { $missing.Add("Node.js 18 or newer (found $(& node --version))") }
if (-not $npm) { $missing.Add('npm (not on PATH; it ships with Node.js)') }
if (-not (Test-Path -LiteralPath (Join-Path $frontend 'node_modules/vite'))) {
    $missing.Add('Front-end packages: run `npm ci` in platform/frontend')
}

# Postgres runs in Docker (docker-compose.dev.yml), so Postgres needs Docker with Compose and a running daemon.
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    $missing.Add('Postgres: Docker Desktop is not installed (docker is not on PATH); the demo Postgres runs in Docker')
} else {
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { $missing.Add('Postgres: Docker Compose v2 (`docker compose`) is not available') }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { $missing.Add('Postgres: Docker Desktop is installed but not running; start it') }
}

$inputs = Join-Path $repoRoot $InputsDir
$explanations = Join-Path $repoRoot $ExplanationsDir
$required = @((Join-Path $repoRoot $ScoredEdges), (Join-Path $repoRoot "$ScoredEdges.log.json"))
$researchPython = Join-Path $repoRoot '.venv312/Scripts/python.exe'
if ($FromProcessedData -and -not (Test-Path -LiteralPath $researchPython)) {
    $missing.Add('Research Python: .venv312 (scripts/bootstrap.ps1 -Only research)')
}
foreach ($tenant in $tenants) {
    if ($FromProcessedData) { continue }      # built below from data/processed/
    foreach ($name in @("tenant_${tenant}_rings.parquet", "tenant_${tenant}_rings.parquet.log.json", "tenant_${tenant}_edge_ids.parquet")) {
        $required += Join-Path $inputs $name
    }
    foreach ($name in @("explanations_${tenant}_1.parquet", "explanations_${tenant}_1.parquet.log.json")) {
        $required += Join-Path $explanations $name
    }
}
if ($R11History) {
    # R11's retrain reads the bank's visible scores (l6.retrain.label_scores_template, docs/R11.md).
    foreach ($tenant in $supervisorTenants) {
        $required += Join-Path $repoRoot "data/tenant_visible/scored_edges_visible_${tenant}_gine_causal_1.parquet.log.json"
    }
}

# The L4 service: its own environment (explainability/requirements-serve.txt) and the research inputs it
# reads (explainability/README.md section 24).
$venvXai = Join-Path (Split-Path -Parent $repoRoot) 'venv-xai/Scripts/python.exe'
$xaiPython = if ($env:XAI_PYTHON) { $env:XAI_PYTHON } elseif (Test-Path -LiteralPath $venvXai) { $venvXai } else { $null }
if (-not $xaiPython) {
    $missing.Add('L4 Python: a venv with explainability/requirements-serve.txt at ..\venv-xai, or set XAI_PYTHON')
}
foreach ($name in @('data/processed/amlworld_train.parquet', 'data/processed/amlworld_val.parquet',
        'data/processed/amlworld_test.parquet', 'data/processed/amlworld_gfp_features_test.parquet',
        'experiments/R1_gine_causal/embeddings_test_seed1.parquet',
        'experiments/R2_b0/gfpxgb_scores/model_seed1.json', 'experiments/R2_b0/gfpxgb_scores/scores_test_seed1.parquet',
        'experiments/R4_partition/affinity/affinity.json', 'experiments/R4_partition/runs/average/seed1/config.yaml')) {
    $required += Join-Path $repoRoot $name
}
foreach ($file in $required) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { $missing.Add("Data file: $file (see README, 'Data')") }
}

if ($missing.Count -gt 0) {
    Write-Host 'Cannot start the demo. Missing:' -ForegroundColor Red
    foreach ($item in $missing) { Write-Host "  - $item" }
    exit 1
}
Write-Host "Found Python ($python), Node $(& node --version), npm $(& npm --version), Docker; all input files present."

$runDemo = Join-Path $PSScriptRoot 'run-demo.ps1'
if ($FromProcessedData) {
    foreach ($tenant in $tenants) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'e2e_demo.ps1') `
            -Tenant $tenant -TimeOriginUtc $TimeOriginUtc -ResearchPython $researchPython -XaiPython $xaiPython -PrepareOnly
        if ($LASTEXITCODE -ne 0) { throw "Building or explaining bank $tenant's rings failed; see the messages above." }
    }
}
# R11's history needs R11's seed-1 config: its retrain labels come from the rings the demo loads.
$configPath = if ($PlatformConfig) { $PlatformConfig } elseif ($R11History) { 'platform/out/r11/config_seed1.yaml' } else { 'platform/config.yaml' }
if ($R11History -and -not $PlatformConfig) {
    Push-Location -LiteralPath (Join-Path $repoRoot 'platform')
    try {
        & $python -m experiments.r11_seed_config --seed 1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not write the R11 seed-1 config.' }
    } finally { Pop-Location }
}
$env:PYTHON = $python
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runDemo -Down -DropVolume
if ($LASTEXITCODE -ne 0) { throw 'Could not stop the previous demo.' }
# A server left on these ports would answer the health checks in place of the new one.
foreach ($port in @(8000, $WebPort, $L4Port)) {
    $holder = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($holder) {
        $name = (Get-Process -Id $holder.OwningProcess -ErrorAction SilentlyContinue).ProcessName
        throw "Port $port is in use by process $($holder.OwningProcess) ($name). Stop it, then rerun."
    }
}

# L4 is configured for banks 12 and 20 only (explainability/config.yaml tenants.banks); the R11
# history demo runs without it, so a partial verdict there says regeneration is unavailable.
$runtime = Join-Path $repoRoot 'platform/out/demo'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$l4 = $null
$xaiArgs = ''
if (-not $R11History) {
    # L4 explains the rings the demo loads: give it exactly those files.
    $l4Inputs = Join-Path $repoRoot 'results/xai/tenant/inputs'
    New-Item -ItemType Directory -Path $l4Inputs -Force | Out-Null
    foreach ($tenant in $tenants) {
        foreach ($name in @("tenant_${tenant}_rings.parquet", "tenant_${tenant}_edge_ids.parquet")) {
            Copy-Item -LiteralPath (Join-Path $inputs $name) -Destination (Join-Path $l4Inputs $name) -Force
        }
    }
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $xaiToken = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $l4Err = Join-Path $runtime 'l4.err.log'
    $env:RINGSHIELD_XAI_TOKEN = $xaiToken
    $l4 = Start-Process -FilePath $xaiPython -ArgumentList @('-m', 'explainability.serve', '--tenants', ($tenants -join ','),
        '--data-root', "`"$repoRoot`"", '--port', [string]$L4Port) -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime 'l4.out.log') -RedirectStandardError $l4Err
    Remove-Item Env:RINGSHIELD_XAI_TOKEN
    Write-Host 'Starting the L4 regeneration service...'
    $l4Ready = $false
    for ($attempt = 0; $attempt -lt 60 -and -not $l4Ready; $attempt++) {
        $l4.Refresh()
        if ($l4.HasExited) { throw "The L4 service exited; inspect $l4Err." }
        try { $l4Ready = (Invoke-RestMethod -Uri "http://127.0.0.1:$L4Port/health" -TimeoutSec 2).status -eq 'ok' }
        catch { Start-Sleep -Seconds 2 }
    }
    if (-not $l4Ready) { Stop-Process -Id $l4.Id -Force; throw "The L4 service did not become ready; inspect $l4Err." }
    $xaiArgs = "-XaiUrl 'http://127.0.0.1:$L4Port' -XaiToken '$xaiToken'"
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '$runDemo' -Tenants $($tenants -join ',') -SupervisorTenants $($supervisorTenants -join ',') -TimeOriginUtc '$TimeOriginUtc' -RingsDir '$InputsDir' -EdgeIdsDir '$InputsDir' -ExplanationsDir '$ExplanationsDir' -PlatformConfig '$configPath' -ScoredEdges '$ScoredEdges' $xaiArgs -SkipStreamlit; exit `$LASTEXITCODE"
if ($LASTEXITCODE -ne 0) { if ($l4) { Stop-Process -Id $l4.Id -Force }; throw 'run-demo.ps1 failed; see the messages above.' }

if ($R11History) {
    $db = '127.0.0.1:' + $(if ($env:RINGSHIELD_DEMO_POSTGRES_PORT) { $env:RINGSHIELD_DEMO_POSTGRES_PORT } else { '55433' })
    $env:RINGSHIELD_DATABASE_URL = "postgresql+psycopg://ringshield_test_app:test-app-only@$db/ringshield?options=-c%20role%3Dringshield_api"
    $env:RINGSHIELD_LOADER_DATABASE_URL = "postgresql+psycopg://ringshield_test_loader:test-loader-only@$db/ringshield?options=-c%20role%3Dringshield_loader"
    $env:RINGSHIELD_SIMULATOR_DATABASE_URL = "postgresql+psycopg://ringshield_test_simulator:test-simulator-only@$db/ringshield?options=-c%20role%3Dringshield_simulator"
    $env:RINGSHIELD_PLATFORM_CONFIG = Join-Path $repoRoot $configPath
    $env:RINGSHIELD_TIME_ORIGIN_UTC = $TimeOriginUtc
    $env:PYTHON_DOTENV_DISABLED = '1'
    Push-Location -LiteralPath (Join-Path $repoRoot 'platform')
    try {
        foreach ($tenant in $supervisorTenants) {
            Write-Host "Adding R11's history to bank ${tenant}: simulated verdicts and a gated retrain (about 15 minutes)..."
            & $python -m experiments.r11_gated_retrain --tenant-id $tenant --accuracy 0.90 --out-root (Join-Path $runtime "r11_T$tenant")
            if ($LASTEXITCODE -ne 0) { throw "R11 history for bank $tenant failed with exit code $LASTEXITCODE." }
        }
    } finally { Pop-Location }
}

Write-Host 'Building the React app (production build)...'
$env:VITE_API_URL = 'http://127.0.0.1:8000'
Push-Location -LiteralPath $frontend
try {
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw 'npm run build failed.' }
} finally { Pop-Location }

$webOut = Join-Path $runtime 'web.out.log'
$webErr = Join-Path $runtime 'web.err.log'
$vite = Join-Path $frontend 'node_modules/vite/bin/vite.js'
$web = Start-Process -FilePath $node.Source -ArgumentList @("`"$vite`"", 'preview', '--host', 'localhost',
    '--port', [string]$WebPort, '--strictPort') -WorkingDirectory $frontend -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $webOut -RedirectStandardError $webErr
# Register with run-demo.ps1's process list so `run-demo.ps1 -Down` stops the web server too.
$pidFile = Join-Path $runtime 'processes.json'
# Unroll the array: Windows PowerShell 5.1 would otherwise save it nested as {"value": [...], "Count": n}.
$processes = [System.Collections.Generic.List[object]]::new()
(Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json) | ForEach-Object { $processes.Add($_) }
foreach ($entry in @(@($web, 'web'), @($l4, 'l4')) | Where-Object { $_[0] }) {
    $processes.Add([pscustomobject]@{ Id = $entry[0].Id; Name = $entry[0].ProcessName;
        StartTicks = $entry[0].StartTime.ToUniversalTime().Ticks; Kind = $entry[1] })
}
ConvertTo-Json -InputObject @($processes) | Set-Content -LiteralPath $pidFile -Encoding UTF8

$url = "http://localhost:$WebPort"
$ready = $false
for ($attempt = 0; $attempt -lt 30 -and -not $ready; $attempt++) {
    $web.Refresh()
    if ($web.HasExited) { throw "The web server exited; inspect $webErr." }
    try { $ready = (Invoke-WebRequest -Uri $url -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200 }
    catch { Start-Sleep -Seconds 1 }
}
if (-not $ready) { throw "The web server did not answer at $url; inspect $webErr." }

$credentials = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $repoRoot 'platform/demo-credentials.txt') -Encoding UTF8) {
    $match = [regex]::Match($line, '^([^=]+)=(.*)$')
    if ($match.Success) { $credentials[$match.Groups[1].Value] = $match.Groups[2].Value }
}
$logins = @($tenants | ForEach-Object { , @("Analyst, bank $_", "tenant_${_}_analyst") }) +
    @($supervisorTenants | ForEach-Object { , @("Supervisor, bank $_", "tenant_${_}_supervisor") }) +
    @(, @('Administrator', 'admin'))
Write-Host ''
Write-Host "RingShield demo is ready: $url" -ForegroundColor Green
Write-Host '(use localhost, not 127.0.0.1: the API accepts this origin only)'
foreach ($login in $logins) {
    Write-Host ("  {0,-20} {1,-34} {2}" -f $login[0], $credentials["$($login[1])_email"], $credentials["$($login[1])_password"])
}
Write-Host 'Stop with: .\scripts\run-demo.ps1 -Down'
