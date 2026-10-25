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

    Logins: an analyst at banks 12 and 20, a supervisor at bank 12, and an administrator.
    Stop everything with: .\scripts\run-demo.ps1 -Down
.EXAMPLE
    .\scripts\demo.ps1
#>
[CmdletBinding()]
param(
    [string]$InputsDir = 'data/platform_tenant_runs/gine_causal_seed1',
    [string]$ScoredEdges = 'contract/out/scored_edges_gine_causal_1.parquet',
    [string]$TimeOriginUtc = '2022-08-31T23:59:50Z',
    [int]$WebPort = 5173
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $repoRoot 'platform/frontend'
$tenants = @('12', '20')
$supervisorTenants = @('12')
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
$required = @((Join-Path $repoRoot $ScoredEdges), (Join-Path $repoRoot "$ScoredEdges.log.json"))
foreach ($tenant in $tenants) {
    foreach ($name in @("tenant_${tenant}_rings.parquet", "tenant_${tenant}_rings.parquet.log.json",
            "tenant_${tenant}_edge_ids.parquet", "explanations_${tenant}_1.parquet", "explanations_${tenant}_1.parquet.log.json")) {
        $required += Join-Path $inputs $name
    }
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
$env:PYTHON = $python
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runDemo -Down -DropVolume
if ($LASTEXITCODE -ne 0) { throw 'Could not stop the previous demo.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '$runDemo' -Tenants $($tenants -join ',') -SupervisorTenants $($supervisorTenants -join ',') -TimeOriginUtc '$TimeOriginUtc' -RingsDir '$InputsDir' -EdgeIdsDir '$InputsDir' -ExplanationsDir '$InputsDir' -ScoredEdges '$ScoredEdges' -SkipStreamlit; exit `$LASTEXITCODE"
if ($LASTEXITCODE -ne 0) { throw 'run-demo.ps1 failed; see the messages above.' }

Write-Host 'Building the React app (production build)...'
$env:VITE_API_URL = 'http://127.0.0.1:8000'
Push-Location -LiteralPath $frontend
try {
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw 'npm run build failed.' }
} finally { Pop-Location }

$runtime = Join-Path $repoRoot 'platform/out/demo'
$webOut = Join-Path $runtime 'web.out.log'
$webErr = Join-Path $runtime 'web.err.log'
$vite = Join-Path $frontend 'node_modules/vite/bin/vite.js'
$web = Start-Process -FilePath $node.Source -ArgumentList @("`"$vite`"", 'preview', '--host', 'localhost',
    '--port', [string]$WebPort, '--strictPort') -WorkingDirectory $frontend -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $webOut -RedirectStandardError $webErr
# Register with run-demo.ps1's process list so `run-demo.ps1 -Down` stops the web server too.
$pidFile = Join-Path $runtime 'processes.json'
$processes = @(Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json)
$processes += [pscustomobject]@{ Id = $web.Id; Name = $web.ProcessName;
    StartTicks = $web.StartTime.ToUniversalTime().Ticks; Kind = 'web' }
$processes | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8

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
$logins = @(
    @('Analyst, bank 12', 'tenant_12_analyst'), @('Analyst, bank 20', 'tenant_20_analyst'),
    @('Supervisor, bank 12', 'tenant_12_supervisor'), @('Administrator', 'admin'))
Write-Host ''
Write-Host "RingShield demo is ready: $url" -ForegroundColor Green
Write-Host '(use localhost, not 127.0.0.1: the API accepts this origin only)'
foreach ($login in $logins) {
    Write-Host ("  {0,-20} {1,-34} {2}" -f $login[0], $credentials["$($login[1])_email"], $credentials["$($login[1])_password"])
}
Write-Host 'Stop with: .\scripts\run-demo.ps1 -Down'
