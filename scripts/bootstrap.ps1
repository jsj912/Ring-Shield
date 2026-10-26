#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Creates the project's Python environments from exact pins, and installs the front end's packages.
.DESCRIPTION
    The parts of the project pin different versions of the same packages, so they live in separate
    environments rather than one. Unifying the pins would change the versions that produced the
    reported numbers.

      research  .venv312            requirements-lock.txt   L0-L3, evaluation, tables. The exact
                                                            versions the shipped R4 runs recorded
                                                            (pandas 3.0.5, numpy 2.5.3, torch 2.5.1+cu121).
      xai       ..\venv-xai          explainability/requirements-test.txt   L4 and its service
                                                            (pandas 2.3.3, scikit-learn 1.8.0).
      platform  ..\venv-platform     requirements-dev.txt   L5/L6 API, workers and their tests
                                                            (pandas 2.2.3, scikit-learn 1.6.1).
      elliptic  .venv-elliptic       elliptic/requirements.txt   Phase 0-3 baselines (E1-E3) and the
                                                            pyvis graph visualisations.

    ..\venv-xai and ..\venv-platform sit next to the repository because scripts/demo.ps1 and
    scripts/run-demo.ps1 look for them there.

    torch is the CUDA 12.1 build; requirements-lock.txt names its index. Installing torch on its own:
      pip install torch --index-url https://download.pytorch.org/whl/cu121
    A machine without an NVIDIA GPU still runs everything except detector training (R1, R6).

    Requires the Python launcher (py) with Python 3.12, and Node.js 18+ for the front end.
.EXAMPLE
    .\scripts\bootstrap.ps1
.EXAMPLE
    .\scripts\bootstrap.ps1 -Only platform,xai
#>
[CmdletBinding()]
param(
    [ValidateSet('research', 'xai', 'platform', 'elliptic', 'frontend')]
    [string[]]$Only = @('research', 'xai', 'platform', 'elliptic', 'frontend'),
    [string]$PythonVersion = '3.12'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$parent = Split-Path -Parent $repoRoot
$envs = [ordered]@{
    research = @{ Path = Join-Path $repoRoot '.venv312'; Requirements = 'requirements-lock.txt' }
    xai      = @{ Path = Join-Path $parent 'venv-xai'; Requirements = 'explainability/requirements-test.txt' }
    platform = @{ Path = Join-Path $parent 'venv-platform'; Requirements = 'requirements-dev.txt' }
    elliptic = @{ Path = Join-Path $repoRoot '.venv-elliptic'; Requirements = 'elliptic/requirements.txt' }
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "The Python launcher (py) is not on PATH. Install Python $PythonVersion from python.org, then rerun."
}
& py "-$PythonVersion" --version *> $null
if ($LASTEXITCODE -ne 0) { throw "Python $PythonVersion is not installed (py -$PythonVersion failed)." }

foreach ($name in $envs.Keys) {
    if ($Only -notcontains $name) { continue }
    $venv = $envs[$name].Path
    $requirements = Join-Path $repoRoot $envs[$name].Requirements
    $python = Join-Path $venv 'Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        Write-Host "== ${name}: creating $venv"
        & py "-$PythonVersion" -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "Could not create $venv." }
    } else {
        Write-Host "== ${name}: $venv exists; installing into it"
    }
    & $python -m pip install --upgrade pip
    & $python -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "pip install -r $($envs[$name].Requirements) failed for $name." }
}

if ($Only -contains 'frontend') {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw 'npm is not on PATH. Install Node.js 18 or newer, then rerun with -Only frontend.'
    }
    Write-Host '== frontend: npm ci'
    & npm ci --prefix (Join-Path $repoRoot 'platform/frontend')
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
}
Write-Host 'Environments ready. Next: README, "Data", then .\scripts\demo.ps1'
