#!/usr/bin/env pwsh
<#
.SYNOPSIS
    One-command end-to-end run: research rings -> L4 explanations -> platform DB, API and dashboard.
.DESCRIPTION
    For one tenant (bank) and detector seed 1:
      1. builds the tenant's rings from its visible edges (platform/jobs/build_tenant_rings.py),
      2. explains them (python -m explainability.tenant),
      3. loads everything into the local demo database and starts the API and dashboard
         (scripts/run-demo.ps1).
    Three Python environments are used because the three parts pin different packages:
    the research venv (ringshield), the XAI venv (explainability/requirements-serve.txt) and
    the platform venv (platform/requirements.txt). See docs/E2E_TESTING.md.
    Stop everything afterwards with: scripts/run-demo.ps1 -Down
#>
[CmdletBinding()]
param(
    [int]$Tenant = 12,
    [string]$TimeOriginUtc = '2022-08-31T23:59:50Z',
    [string]$ResearchPython = '.venv312/Scripts/python.exe',
    [Parameter(Mandatory = $true)][string]$XaiPython,
    [Parameter(Mandatory = $true)][string]$PlatformPython
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Resolve-Python {
    param([string]$Path, [string]$Name)
    $full = if ([System.IO.Path]::IsPathRooted($Path)) { $Path } else { Join-Path $RepoRoot $Path }
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { throw "$Name Python not found: $full" }
    return (Resolve-Path -LiteralPath $full).Path
}

function Invoke-Step {
    param([string]$Name, [scriptblock]$Body)
    Write-Host "== $Name"
    & $Body
    if ($LASTEXITCODE -ne 0) { throw "Step '$Name' failed with exit code $LASTEXITCODE." }
}

$research = Resolve-Python $ResearchPython 'Research'
$xai = Resolve-Python $XaiPython 'XAI'
$platform = Resolve-Python $PlatformPython 'Platform'

Invoke-Step 'check Docker engine' { docker version --format '{{.Server.Version}}' }

# Streamlit asks for an email on its first run; a background dashboard can never answer, so it never starts.
$streamlitDir = Join-Path $env:USERPROFILE '.streamlit'
$streamlitCredentials = Join-Path $streamlitDir 'credentials.toml'
if (-not (Test-Path -LiteralPath $streamlitCredentials)) {
    New-Item -ItemType Directory -Force -Path $streamlitDir | Out-Null
    Set-Content -LiteralPath $streamlitCredentials -Encoding ascii -Value "[general]`nemail = `"`""
}

$runs = 'data/platform_tenant_runs/gine_causal_seed1'
Invoke-Step "build tenant $Tenant rings" {
    & $research platform/jobs/build_tenant_rings.py --tenant-id $Tenant --output-dir $runs
}

# explainability.tenant reads the tenant's rings and edge ids from results/xai/tenant/inputs.
$xaiInputs = 'results/xai/tenant/inputs'
New-Item -ItemType Directory -Force -Path $xaiInputs | Out-Null
Copy-Item -Force -Path (Join-Path $runs "tenant_${Tenant}_*") -Destination $xaiInputs
Invoke-Step "explain tenant $Tenant rings" { & $xai -m explainability.tenant --bank $Tenant }

$env:PATH = "$(Split-Path -Parent $platform);$env:PATH"
Invoke-Step 'load demo database and start API and dashboard' {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run-demo.ps1') `
        -Tenants $Tenant -TimeOriginUtc $TimeOriginUtc `
        -RingsDir $runs -EdgeIdsDir $runs `
        -ScoredEdges 'contract/out/scored_edges_gine_causal_1.parquet' `
        -ExplanationsDir 'results/xai/tenant'
}

Write-Host "Done. Dashboard: http://127.0.0.1:8501  API: http://127.0.0.1:8000"
Write-Host "Logins: platform/demo-credentials.txt (tenant_${Tenant}_analyst_*). Stop with scripts/run-demo.ps1 -Down"
