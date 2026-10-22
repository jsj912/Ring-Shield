#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Start or stop an isolated local RingShield demo database and Windows services.
.DESCRIPTION
    Loads only the requested tenants' visible edges and their tenant-scoped rings
    and explanations. Use -ValidateOnly for an offline preflight; use -Down to
    stop the local API, dashboard, and demo containers.
#>
[CmdletBinding()]
param(
    [string[]]$Tenants = @('12', '20'),
    [string]$TimeOriginUtc,
    [string]$RingsDir,
    [string]$EdgeIdsDir,
    [string]$ScoredEdges = 'contract/out/scored_edges_gine_causal_1.parquet',
    [string]$ExplanationsDir,
    [string]$XaiUrl,
    [string]$XaiToken,
    [switch]$Down,
    [switch]$DropVolume,
    [switch]$ResetPasswords,
    [switch]$ValidateOnly,
    [switch]$StartFakeL4,
    [switch]$DefinitionsOnly,
    [int]$PostgresTimeoutSeconds = 120
)

$script:RepoRoot = Split-Path -Parent $PSScriptRoot
$script:ComposeFile = Join-Path $script:RepoRoot 'docker-compose.dev.yml'
$script:ProjectName = 'ringshield-demo'
$script:CredentialsPath = Join-Path $script:RepoRoot 'platform/demo-credentials.txt'
$script:RuntimeDir = Join-Path $script:RepoRoot 'platform/out/demo'

function Resolve-DemoPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $script:RepoRoot $Path))
}

function Assert-TimeOriginUtc {
    param([AllowNull()][string]$Value)
    $definition = 'the UTC instant of loader timestamp 0: first transaction day 00:00 UTC minus 10 seconds (for example 2022-08-31T23:59:50Z).'
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "-TimeOriginUtc is required and must be an ISO-8601 instant with a UTC offset or Z. It means $definition"
    }
    $isoInstant = '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$'
    $parsedOrigin = [DateTimeOffset]::MinValue
    $validDate = [DateTimeOffset]::TryParse(
        $Value,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None,
        [ref]$parsedOrigin
    )
    if ($Value -notmatch $isoInstant -or -not $validDate) {
        throw "Invalid -TimeOriginUtc '$Value'. Supply an ISO-8601 instant with a UTC offset or Z. It means $definition"
    }
}

function Resolve-DemoL4Options {
    param([string]$Url, [string]$Token, [switch]$UseFakeServer)
    if ($UseFakeServer -and -not [string]::IsNullOrWhiteSpace($Url)) {
        throw '-StartFakeL4 cannot be combined with -XaiUrl.'
    }
    if (-not [string]::IsNullOrWhiteSpace($Url)) {
        $parsed = $null
        if (-not [System.Uri]::TryCreate($Url, [System.UriKind]::Absolute, [ref]$parsed) -or
                $parsed.Scheme -notin @('http', 'https') -or
                $parsed.Host -notin @('localhost', '127.0.0.1', '::1') -or
                -not [string]::IsNullOrEmpty($parsed.UserInfo) -or
                -not [string]::IsNullOrEmpty($parsed.Query) -or
                -not [string]::IsNullOrEmpty($parsed.Fragment)) {
            throw '-XaiUrl must be an absolute HTTP(S) URL on localhost, 127.0.0.1, or ::1.'
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($Token) -and
            [string]::IsNullOrWhiteSpace($Url) -and -not $UseFakeServer) {
        throw '-XaiToken requires -XaiUrl or -StartFakeL4.'
    }
    return [pscustomobject]@{ Url = $Url; Token = $Token; UseFakeServer = [bool]$UseFakeServer }
}

function New-DemoXaiToken {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
}

function ConvertTo-DemoTenantIds {
    param([string[]]$TenantValues)
    $tenantIds = [System.Collections.Generic.List[int]]::new()
    $seenTenantIds = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($tenantValue in $TenantValues) {
        if ($null -eq $tenantValue) { continue }
        foreach ($tenantToken in ($tenantValue -split '[,\s]+')) {
            if ([string]::IsNullOrEmpty($tenantToken)) { continue }
            if ($tenantToken -notmatch '^\d+$') {
                throw "Invalid -Tenants token '$tenantToken': expected digits only."
            }
            try {
                $tenantId = [int]::Parse(
                    $tenantToken,
                    [Globalization.NumberStyles]::None,
                    [Globalization.CultureInfo]::InvariantCulture
                )
            } catch {
                throw "Invalid -Tenants token '$tenantToken': value is outside the supported integer range."
            }
            if ($tenantId -le 0) {
                throw "Invalid -Tenants token '$tenantToken': bank IDs must be positive."
            }
            if (-not $seenTenantIds.Add($tenantId)) {
                throw "Duplicate -Tenants token '$tenantToken'."
            }
            $tenantIds.Add($tenantId)
        }
    }
    if ($tenantIds.Count -eq 0) { throw 'Select at least one bank with -Tenants.' }
    return ,$tenantIds.ToArray()
}

function Get-PlatformConfigPath {
    param([string]$Key)
    $configPath = Join-Path $script:RepoRoot 'platform/config.yaml'
    $match = Select-String -LiteralPath $configPath -Pattern ("^\s*" + [regex]::Escape($Key) + ":\s*(.+?)\s*$") -ErrorAction Stop |
        Select-Object -First 1 -ErrorAction Stop
    if (-not $match) { throw "platform/config.yaml is missing '$Key'." }
    $value = $match.Matches[0].Groups[1].Value.Trim().Trim([char]'"').Trim([char]"'")
    if ([string]::IsNullOrWhiteSpace($value)) { throw "platform/config.yaml has an empty '$Key'." }
    return Resolve-DemoPath $value
}

function Get-ConfiguredL4Url {
    $configPath = Join-Path $script:RepoRoot 'platform/config.yaml'
    $match = Select-String -LiteralPath $configPath -Pattern '(?m)^\s+regenerate_url:\s*(.*?)\s*$' -ErrorAction Stop |
        Select-Object -First 1
    if (-not $match) { throw 'platform/config.yaml is missing l4.regenerate_url.' }
    $value = $match.Matches[0].Groups[1].Value.Trim().Trim([char]'"').Trim([char]"'")
    if ($value -eq 'null' -or [string]::IsNullOrWhiteSpace($value)) { return $null }
    return $value
}

function Find-ForbiddenPathValue {
    param([object]$Value)
    if ($null -eq $Value) { return $null }
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        foreach ($property in $Value.PSObject.Properties) {
            $found = Find-ForbiddenPathValue $property.Value
            if ($found) { return $found }
        }
    } elseif ($Value -is [System.Collections.IDictionary]) {
        foreach ($item in $Value.Values) {
            $found = Find-ForbiddenPathValue $item
            if ($found) { return $found }
        }
    } elseif ($Value -is [System.Array] -or $Value -is [System.Collections.IList]) {
        foreach ($item in $Value) {
            $found = Find-ForbiddenPathValue $item
            if ($found) { return $found }
        }
    } elseif ($Value -is [string]) {
        $normalized = $Value.Replace('\', '/').ToLowerInvariant()
        $parts = $normalized -split '/'
        foreach ($part in $parts) {
            if ($part.StartsWith('labels_') -or $part.Contains('ground_truth')) {
                return $Value
            }
        }
    }
    return $null
}

function Assert-SafeDemoPath {
    param([string]$Path)
    $normalized = $Path.Replace('\', '/').ToLowerInvariant()
    foreach ($part in ($normalized -split '/')) {
        if ($part.StartsWith('labels_') -or $part.Contains('ground_truth')) {
            throw "Refusing label/ground-truth input path: $Path"
        }
    }
}

function Read-DemoJson {
    param([string]$Path, [string]$Description)
    try {
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop)
    } catch {
        throw "Could not read $Description JSON: $Path ($($_.Exception.Message))"
    }
}

function ConvertFrom-ParquetRowCountOutput {
    param([object[]]$Output, [int]$ExitCode, [string]$Path)
    $outputText = ($Output | ForEach-Object { "$_" }) -join [Environment]::NewLine
    $outputText = $outputText.Trim()
    if ($ExitCode -ne 0) {
        if ([string]::IsNullOrWhiteSpace($outputText)) { $outputText = 'the count command returned no error text' }
        throw "Step 'read parquet row count' failed for '$Path' (exit code $ExitCode): $outputText"
    }
    if ([string]::IsNullOrWhiteSpace($outputText)) {
        throw "Step 'read parquet row count' failed for '$Path': the command returned empty output."
    }
    $parsed = [long]0
    if (-not [long]::TryParse($outputText, [Globalization.NumberStyles]::None,
            [Globalization.CultureInfo]::InvariantCulture, [ref]$parsed) -or $parsed -lt 0) {
        throw "Step 'read parquet row count' failed for '$Path': expected one non-negative integer, got '$outputText'."
    }
    return $parsed
}

function Get-ParquetRowCount {
    param([string]$Python, [string]$Path)
    $output = & $Python 'platform/jobs/count_parquet_rows.py' $Path 2>&1
    $pythonExitCode = $LASTEXITCODE
    return ConvertFrom-ParquetRowCountOutput -Output @($output) -ExitCode $pythonExitCode -Path $Path
}

function Assert-DemoInputs {
    param(
        [int[]]$SelectedTenants,
        [string]$RingFolder,
        [string]$EdgeFolder,
        [string]$ScoreFile,
        [string]$ExplanationFolder
    )
    if ($null -eq $SelectedTenants -or $SelectedTenants.Count -eq 0) {
        throw 'Select at least one bank with -Tenants.'
    }
    if (($SelectedTenants | Where-Object { $_ -le 0 }).Count -gt 0) {
        throw '-Tenants values must be positive bank IDs.'
    }
    if (@($SelectedTenants | Select-Object -Unique).Count -ne $SelectedTenants.Count) {
        throw '-Tenants contains duplicate bank IDs.'
    }
    if ([string]::IsNullOrWhiteSpace($RingFolder)) { throw 'Missing required parameter -RingsDir.' }
    if ([string]::IsNullOrWhiteSpace($EdgeFolder)) { throw 'Missing required parameter -EdgeIdsDir.' }
    if ([string]::IsNullOrWhiteSpace($ExplanationFolder)) { throw 'Missing required parameter -ExplanationsDir.' }

    $ringsPath = Resolve-DemoPath $RingFolder
    $edgePath = Resolve-DemoPath $EdgeFolder
    $scoresPath = Resolve-DemoPath $ScoreFile
    $explanationsPath = Resolve-DemoPath $ExplanationFolder
    foreach ($path in @($ringsPath, $edgePath, $scoresPath, $explanationsPath)) {
        Assert-SafeDemoPath $path
    }
    foreach ($directory in @($ringsPath, $edgePath, $explanationsPath)) {
        if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
            throw "Input directory does not exist: $directory"
        }
        Get-ChildItem -LiteralPath $directory -File -Recurse -ErrorAction Stop | ForEach-Object {
            Assert-SafeDemoPath $_.FullName
        }
    }
    if (-not (Test-Path -LiteralPath $scoresPath -PathType Leaf)) {
        throw "Scored-edges parquet does not exist: $scoresPath"
    }
    $scoreLogPath = "$scoresPath.log.json"
    if (-not (Test-Path -LiteralPath $scoreLogPath -PathType Leaf)) {
        throw "Scored-edges sibling .log.json is required: $scoreLogPath"
    }
    Assert-SafeDemoPath $scoreLogPath
    $scoreLog = Read-DemoJson $scoreLogPath 'scored-edges run log'
    $forbiddenScoreLogValue = Find-ForbiddenPathValue $scoreLog
    if ($forbiddenScoreLogValue) {
        throw "Refusing label/ground-truth path in scored-edges run log: $forbiddenScoreLogValue"
    }
    if ($scoreLog.split -ne 'test') {
        throw "Scored-edges run log must declare split=test: $scoreLogPath"
    }

    $inputFiles = [System.Collections.Generic.List[object]]::new()
    $inputFiles.Add([pscustomobject]@{ Kind = 'scored edges'; Path = $scoresPath; Log = $scoreLogPath })
    foreach ($tenantId in $SelectedTenants) {
        $ring = Join-Path $ringsPath "tenant_${tenantId}_rings.parquet"
        $edgeIds = Join-Path $edgePath "tenant_${tenantId}_edge_ids.parquet"
        $explanation = Join-Path $explanationsPath "explanations_${tenantId}_1.parquet"
        foreach ($file in @($ring, $edgeIds, $explanation)) {
            Assert-SafeDemoPath $file
            if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
                throw "Required tenant $tenantId input file is missing: $file"
            }
        }
        $ringLog = "$ring.log.json"
        $explanationLog = "$explanation.log.json"
        foreach ($logFile in @($ringLog, $explanationLog)) {
            Assert-SafeDemoPath $logFile
            if (-not (Test-Path -LiteralPath $logFile -PathType Leaf)) {
                throw "Required sibling .log.json is missing: $logFile"
            }
            $runLog = Read-DemoJson $logFile 'tenant handoff run log'
            $forbiddenValue = Find-ForbiddenPathValue $runLog
            if ($forbiddenValue) {
                throw "Refusing label/ground-truth path in run log: $forbiddenValue"
            }
        }
        $inputFiles.Add([pscustomobject]@{ Kind = "tenant $tenantId rings"; Path = $ring; Log = $ringLog })
        $inputFiles.Add([pscustomobject]@{ Kind = "tenant $tenantId edge IDs"; Path = $edgeIds; Log = $null })
        $inputFiles.Add([pscustomobject]@{ Kind = "tenant $tenantId explanations"; Path = $explanation; Log = $explanationLog })
    }
    return [pscustomobject]@{ Tenants = $SelectedTenants; RingsDir = $ringsPath;
        EdgeIdsDir = $edgePath; ScoredEdges = $scoresPath; ExplanationsDir = $explanationsPath;
        Inputs = @($inputFiles) }
}

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments, [string]$StepName = $File)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Step '$StepName' failed with exit code $LASTEXITCODE. Command: $File $($Arguments -join ' ')"
    }
}

function Invoke-DemoCompose {
    param([string[]]$ComposeArgs, [string]$StepName = 'Docker Compose')
    Invoke-Checked 'docker' (@('compose', '-p', $script:ProjectName, '-f', $script:ComposeFile) + $ComposeArgs) $StepName
}

function Stop-DemoProcesses {
    $pidFile = Join-Path $script:RuntimeDir 'processes.json'
    if (-not (Test-Path -LiteralPath $pidFile)) { return }
    try { $processes = Get-Content -LiteralPath $pidFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop }
    catch { Write-Warning 'Could not read demo process list; leaving local processes untouched.'; return }
    foreach ($entry in @($processes | Where-Object { $_.Kind -eq 'supervisor' -and $_.StopFile })) {
        try {
            New-Item -ItemType File -Path $entry.StopFile -Force -ErrorAction Stop | Out-Null
            $deadline = [DateTime]::UtcNow.AddSeconds(10)
            while ([DateTime]::UtcNow -lt $deadline -and (Get-Process -Id ([int]$entry.Id) -ErrorAction SilentlyContinue)) {
                Start-Sleep -Milliseconds 200
            }
        } catch { Write-Warning 'Could not signal the demo worker supervisor to stop gracefully.' }
    }
    foreach ($entry in @($processes)) {
        $process = Get-Process -Id ([int]$entry.Id) -ErrorAction SilentlyContinue
        $sameInstance = $false
        if ($process -and $process.ProcessName -eq $entry.Name) {
            try { $sameInstance = $process.StartTime.ToUniversalTime().Ticks -eq [long]$entry.StartTicks }
            catch { $sameInstance = $false }
        }
        if ($sameInstance) {
            try { Stop-Process -Id $process.Id -Force -ErrorAction Stop }
            catch { Write-Warning "Could not stop demo process $($entry.Name) (PID $($entry.Id))." }
        }
        if ($entry.StopFile) { Remove-Item -LiteralPath $entry.StopFile -Force -ErrorAction SilentlyContinue }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

function Save-DemoProcess {
    param([System.Diagnostics.Process]$Process, [string]$Kind, [string]$StopFile)
    $entry = [ordered]@{ Id = $Process.Id; Name = $Process.ProcessName;
        StartTicks = $Process.StartTime.ToUniversalTime().Ticks; Kind = $Kind }
    if ($StopFile) { $entry.StopFile = $StopFile }
    $script:DemoProcesses.Add([pscustomobject]$entry)
    $script:DemoProcesses | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $script:RuntimeDir 'processes.json') `
        -Encoding UTF8 -ErrorAction Stop
}

function Invoke-DemoDown {
    Stop-DemoProcesses
    $composeArgs = @('down', '--remove-orphans')
    if ($DropVolume) { $composeArgs += '--volumes' }
    Invoke-DemoCompose -ComposeArgs $composeArgs -StepName 'stop demo containers'
    if ($DropVolume) {
        Remove-Item -LiteralPath $script:CredentialsPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $script:RuntimeDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host 'Demo containers and the demo database volume were removed.'
    } else {
        Write-Host 'Demo containers were removed; the database volume and demo credentials were kept.'
    }
}

function New-DemoPassword {
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Get-DemoCredentials {
    $values = [ordered]@{}
    if (Test-Path -LiteralPath $script:CredentialsPath) {
        foreach ($line in Get-Content -LiteralPath $script:CredentialsPath -Encoding UTF8 -ErrorAction Stop) {
            $credentialMatch = [regex]::Match($line, '^([^=]+)=(.*)$')
            if ($credentialMatch.Success) { $values[$credentialMatch.Groups[1].Value] = $credentialMatch.Groups[2].Value }
        }
    }
    $added = [System.Collections.Generic.List[string]]::new()
    if (-not $values.Contains('admin_email')) {
        $values['admin_email'] = 'demo-admin@ringshield.local'
        $added.Add("admin_email=$($values.admin_email)")
    }
    if (-not $values.Contains('admin_password')) {
        $values['admin_password'] = New-DemoPassword
        $added.Add("admin_password=$($values.admin_password)")
    }
    foreach ($tenantId in $Tenants) {
        foreach ($role in @('analyst', 'supervisor')) {
            $emailKey = "tenant_${tenantId}_${role}_email"
            $passwordKey = "tenant_${tenantId}_${role}_password"
            if (-not $values.Contains($emailKey)) {
                $values[$emailKey] = "${role}${tenantId}@ringshield.local"
                $added.Add("${emailKey}=$($values[$emailKey])")
            }
            if (-not $values.Contains($passwordKey)) {
                $values[$passwordKey] = New-DemoPassword
                $added.Add("${passwordKey}=$($values[$passwordKey])")
            }
        }
    }
    if ($added.Count -gt 0) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $script:CredentialsPath) -Force -ErrorAction Stop | Out-Null
        if (Test-Path -LiteralPath $script:CredentialsPath) {
            Add-Content -LiteralPath $script:CredentialsPath -Value $added -Encoding UTF8 -ErrorAction Stop
        } else {
            Set-Content -LiteralPath $script:CredentialsPath -Value $added -Encoding UTF8 -ErrorAction Stop
        }
    }
    return $values
}

function Reset-DemoCredentials {
    param([System.Collections.IDictionary]$Credentials)
    foreach ($key in @($Credentials.Keys)) {
        if ($key -eq 'admin_password' -or $key -match '^tenant_\d+_(analyst|supervisor)_password$') {
            $Credentials[$key] = New-DemoPassword
        }
    }
    return $Credentials
}

function Get-DemoCredentialTenants {
    param([System.Collections.IDictionary]$Credentials)
    $tenantIds = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($key in $Credentials.Keys) {
        $credentialMatch = [regex]::Match($key, '^tenant_(\d+)_(analyst|supervisor)_email$')
        if ($credentialMatch.Success) { [void]$tenantIds.Add([int]$credentialMatch.Groups[1].Value) }
    }
    return @($tenantIds | Sort-Object)
}

function Get-DemoCurrentRevision {
    param([string]$Python, [string]$AdminUrl)
    $env:RINGSHIELD_DEMO_ADMIN_URL = $AdminUrl
    $code = @'
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["RINGSHIELD_DEMO_ADMIN_URL"])
try:
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL")).scalar_one()
        if exists:
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            print(",".join(rows))
        else:
            print("base")
finally:
    engine.dispose()
'@
    $output = $code | & $Python -
    $pythonExitCode = $LASTEXITCODE
    Remove-Item Env:RINGSHIELD_DEMO_ADMIN_URL -ErrorAction SilentlyContinue
    if ($pythonExitCode -ne 0) { throw "Step 'inspect demo migration revision' failed with exit code $pythonExitCode." }
    $revision = ($output | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($revision)) {
        throw "Step 'inspect demo migration revision' failed: Python returned empty output."
    }
    return $revision
}

function Invoke-PsqlFile {
    param([string]$FilePath)
    $sql = Get-Content -LiteralPath $FilePath -Raw -Encoding UTF8 -ErrorAction Stop
    $sql | & docker compose -p $script:ProjectName -f $script:ComposeFile exec -T postgres-demo psql -U postgres -d ringshield -v ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) { throw "Step 'apply Postgres role setup' failed while applying $FilePath (exit code $LASTEXITCODE)." }
}

function Get-DemoDatabaseUrls {
    param([int]$Port, [string]$PostgresPassword)
    $escapedPassword = [System.Uri]::EscapeDataString($PostgresPassword)
    $dbHostPort = "127.0.0.1:$Port"
    return @{
        Admin = "postgresql+psycopg://postgres:${escapedPassword}@${dbHostPort}/ringshield"
        App = "postgresql+psycopg://ringshield_test_app:test-app-only@${dbHostPort}/ringshield?options=-c%20role%3Dringshield_api"
        Auth = "postgresql+psycopg://ringshield_test_auth:test-auth-only@${dbHostPort}/ringshield?options=-c%20role%3Dringshield_auth"
        Loader = "postgresql+psycopg://ringshield_test_loader:test-loader-only@${dbHostPort}/ringshield?options=-c%20role%3Dringshield_loader"
    }
}

function Write-DemoUsers {
    param([string]$Python, [string]$AdminUrl,
          [System.Collections.IDictionary]$Credentials, [int[]]$SelectedTenants,
          [switch]$AuditPasswordReset)
    $users = [System.Collections.Generic.List[object]]::new()
    $users.Add([pscustomobject]@{ TenantId = 'None'; Email = $Credentials.admin_email;
        Password = $Credentials.admin_password; Role = 'admin' })
    foreach ($tenantId in $SelectedTenants) {
        foreach ($role in @('analyst', 'supervisor')) {
            $users.Add([pscustomobject]@{ TenantId = [string]$tenantId;
                Email = $Credentials["tenant_${tenantId}_${role}_email"];
                Password = $Credentials["tenant_${tenantId}_${role}_password"]; Role = $role })
        }
    }
    $usersJson = ConvertTo-Json -InputObject @($users) -Compress
    $env:RINGSHIELD_DEMO_ADMIN_URL = $AdminUrl
    $env:RINGSHIELD_DEMO_USERS_JSON = $usersJson
    $env:RINGSHIELD_DEMO_CREDENTIALS_JSON = ConvertTo-Json -InputObject $Credentials -Compress
    $env:RINGSHIELD_DEMO_CREDENTIALS_PATH = $script:CredentialsPath
    $env:RINGSHIELD_DEMO_PASSWORD_RESET = if ($AuditPasswordReset) { '1' } else { '0' }
    try {
        Invoke-Checked $Python @('platform/jobs/provision_demo_users.py') 'provision demo login users'
    } finally {
        Remove-Item Env:RINGSHIELD_DEMO_ADMIN_URL -ErrorAction SilentlyContinue
        Remove-Item Env:RINGSHIELD_DEMO_USERS_JSON -ErrorAction SilentlyContinue
        Remove-Item Env:RINGSHIELD_DEMO_CREDENTIALS_JSON -ErrorAction SilentlyContinue
        Remove-Item Env:RINGSHIELD_DEMO_CREDENTIALS_PATH -ErrorAction SilentlyContinue
        Remove-Item Env:RINGSHIELD_DEMO_PASSWORD_RESET -ErrorAction SilentlyContinue
    }
}

function Assert-AppRoleIsRestricted {
    param([string]$Python, [string]$AdminUrl)
    $env:RINGSHIELD_DEMO_ADMIN_URL = $AdminUrl
    $code = @'
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["RINGSHIELD_DEMO_ADMIN_URL"])
try:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='ringshield_api'")).one()
        owners = conn.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner='ringshield_api'")).scalar_one()
        if row.rolsuper or row.rolbypassrls or owners:
            raise SystemExit("ringshield_api must be non-superuser, NO BYPASSRLS, and not own tables")
finally:
    engine.dispose()
'@
    $code | & $Python -
    $pythonExitCode = $LASTEXITCODE
    Remove-Item Env:RINGSHIELD_DEMO_ADMIN_URL -ErrorAction SilentlyContinue
    if ($pythonExitCode -ne 0) { throw "Step 'verify restricted app role' failed with exit code $pythonExitCode." }
}

function Write-DemoCounts {
    param([string]$Python, [string]$AdminUrl, [int[]]$SelectedTenants,
          [hashtable]$ExpectedEdges, [hashtable]$InputEdgeCounts,
          [hashtable]$InputRingCounts, [hashtable]$InputExplanationCounts)
    $env:RINGSHIELD_DEMO_ADMIN_URL = $AdminUrl
    $edgeByTenant = @{}; foreach ($key in @($InputEdgeCounts.Keys)) { $edgeByTenant[[string]$key] = $InputEdgeCounts[$key] }
    $ringByTenant = @{}; foreach ($key in @($InputRingCounts.Keys)) { $ringByTenant[[string]$key] = $InputRingCounts[$key] }
    $explanationByTenant = @{}; foreach ($key in @($InputExplanationCounts.Keys)) { $explanationByTenant[[string]$key] = $InputExplanationCounts[$key] }
    $env:RINGSHIELD_DEMO_TENANTS = ($SelectedTenants -join ',')
    $expectedRows = @{}
    foreach ($tenantId in $SelectedTenants) {
        $expectedRows[[string]$tenantId] = @{
            transactions = $edgeByTenant[[string]$tenantId]
            edge_scores = $edgeByTenant[[string]$tenantId]
            rings = $ringByTenant[[string]$tenantId]
            explanations = $explanationByTenant[[string]$tenantId]
        }
    }
    $env:RINGSHIELD_DEMO_EXPECTED_ROWS = ConvertTo-Json -InputObject $expectedRows -Compress
    $code = @'
import json, os
from sqlalchemy import create_engine, text
tenants = [int(x) for x in os.environ["RINGSHIELD_DEMO_TENANTS"].split(",")]
expected = json.loads(os.environ["RINGSHIELD_DEMO_EXPECTED_ROWS"])
engine = create_engine(os.environ["RINGSHIELD_DEMO_ADMIN_URL"])
try:
    with engine.connect() as conn:
        tables = conn.execute(text("""
            SELECT DISTINCT table_name FROM information_schema.columns
            WHERE table_schema='public' AND column_name='tenant_id'
            ORDER BY table_name
        """)).scalars().all()
        quote = engine.dialect.identifier_preparer.quote
        for table in tables:
            print(f"{table}:")
            for tenant in tenants:
                count = conn.execute(text(f"SELECT count(*) FROM public.{quote(table)} WHERE tenant_id=:tenant"), {"tenant": tenant}).scalar_one()
                print(f"  tenant {tenant}: {count}")
                target = expected.get(str(tenant), {}).get(table)
                if target is not None and count != target:
                    raise SystemExit(f"{table} row count for tenant {tenant} is {count}; expected {target}")
finally:
    engine.dispose()
'@
    $code | & $Python -
    $pythonExitCode = $LASTEXITCODE
    Remove-Item Env:RINGSHIELD_DEMO_ADMIN_URL -ErrorAction SilentlyContinue
    Remove-Item Env:RINGSHIELD_DEMO_TENANTS -ErrorAction SilentlyContinue
    Remove-Item Env:RINGSHIELD_DEMO_EXPECTED_ROWS -ErrorAction SilentlyContinue
    if ($pythonExitCode -ne 0) { throw "Step 'query demo row counts' failed with exit code $pythonExitCode." }
    foreach ($tenantId in $SelectedTenants) {
        $expected = $ExpectedEdges[[string]$tenantId]
        if ($null -ne $expected -and $edgeByTenant[[string]$tenantId] -ne $expected) {
            throw "Tenant $tenantId edge-ID file has $($edgeByTenant[[string]$tenantId]) rows; expected $expected."
        }
        if ($ringByTenant[[string]$tenantId] -ne 5) {
            throw "Tenant $tenantId ring parquet has $($ringByTenant[[string]$tenantId]) rows; expected 5."
        }
    }
}

if ($DefinitionsOnly) { return }
if ($StartFakeL4 -and -not [string]::IsNullOrWhiteSpace($XaiUrl)) {
    throw '-StartFakeL4 cannot be combined with -XaiUrl.'
}
$configuredL4Url = if ($StartFakeL4) { $null } elseif (-not [string]::IsNullOrWhiteSpace($XaiUrl)) { $XaiUrl } else { Get-ConfiguredL4Url }
$script:DemoL4Options = Resolve-DemoL4Options -Url $configuredL4Url -Token $XaiToken -UseFakeServer:$StartFakeL4
$Tenants = ConvertTo-DemoTenantIds -TenantValues $Tenants
if ($ResetPasswords -and $Down) { throw '-ResetPasswords cannot be combined with -Down.' }
if ($ResetPasswords -and $ValidateOnly) { throw '-ResetPasswords cannot be combined with -ValidateOnly.' }
if ($Down -and $ValidateOnly) { throw '-Down and -ValidateOnly cannot be combined.' }
if ($DropVolume -and -not $Down) { throw '-DropVolume can only be used with -Down.' }
if ($Down) {
    try { Invoke-DemoDown }
    catch { Write-Error $_; exit 1 }
    return
}

try { Assert-TimeOriginUtc $TimeOriginUtc }
catch { Write-Error $_; exit 1 }

Push-Location -LiteralPath $script:RepoRoot -ErrorAction Stop
$script:LocationPushed = $true
try {
    $validated = Assert-DemoInputs -SelectedTenants $Tenants -RingFolder $RingsDir `
        -EdgeFolder $EdgeIdsDir -ScoreFile $ScoredEdges -ExplanationFolder $ExplanationsDir
    foreach ($inputFile in $validated.Inputs) { Write-Host ("Preflight found {0}: {1}" -f $inputFile.Kind, $inputFile.Path) }
    if ($ValidateOnly) {
        foreach ($inputFile in $validated.Inputs) { Write-Host ("Found {0}: {1}" -f $inputFile.Kind, $inputFile.Path) }
        Write-Host 'Demo arguments and handoff paths are valid; Docker was not started.'
        return
    }

    $script:EffectiveXaiToken = $script:DemoL4Options.Token
    if (($script:DemoL4Options.UseFakeServer -or -not [string]::IsNullOrWhiteSpace($script:DemoL4Options.Url)) -and
            [string]::IsNullOrWhiteSpace($script:EffectiveXaiToken)) {
        $script:EffectiveXaiToken = New-DemoXaiToken
    }

    $accountMap = Get-PlatformConfigPath 'account_map'
    if (-not (Test-Path -LiteralPath $accountMap -PathType Leaf)) {
        throw "Configured account map is required to seed the tenant registry: $accountMap"
    }
    $modelDir = Get-PlatformConfigPath 'model_dir'
    if (-not (Test-Path -LiteralPath $modelDir -PathType Container)) {
        throw "Configured active model artifact is required by the API health check: $modelDir"
    }

    $docker = Get-Command docker -ErrorAction Stop
    $pythonCommand = Get-Command python -ErrorAction Stop
    $python = $pythonCommand.Source
    $explanationCheckArguments = @('platform/jobs/check_explanations.py')
    foreach ($tenantId in $Tenants) {
        $explanationFile = Join-Path $validated.ExplanationsDir "explanations_${tenantId}_1.parquet"
        $ringsLog = Join-Path $validated.RingsDir "tenant_${tenantId}_rings.parquet.log.json"
        $explanationCheckArguments += @('--explanations', $explanationFile,
            '--run-log', "$explanationFile.log.json", '--rings-log', $ringsLog)
    }
    Invoke-Checked $python $explanationCheckArguments 'validate tenant explanation handoffs (read-only)'
    & $docker.Source info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Step 'check Docker Desktop' failed with exit code $LASTEXITCODE. Start Docker Desktop, then retry." }
    if ($PostgresTimeoutSeconds -lt 10) { throw '-PostgresTimeoutSeconds must be at least 10.' }
    $portText = if ($env:RINGSHIELD_DEMO_POSTGRES_PORT) { $env:RINGSHIELD_DEMO_POSTGRES_PORT } else { '55433' }
    $port = 0
    if (-not [int]::TryParse($portText, [ref]$port) -or $port -lt 1024 -or $port -gt 65535) {
        throw 'RINGSHIELD_DEMO_POSTGRES_PORT must be an available TCP port from 1024 through 65535.'
    }
    $postgresPassword = if ($env:RINGSHIELD_DEMO_POSTGRES_PASSWORD) {
        $env:RINGSHIELD_DEMO_POSTGRES_PASSWORD
    } else { 'ringshield-demo-local' }
    $urls = Get-DemoDatabaseUrls -Port $port -PostgresPassword $postgresPassword

    Write-Host 'Installing pinned platform and test dependencies...'
    Invoke-Checked $python @('-m', 'pip', 'install', '-r', 'requirements-dev.txt') 'install pinned dependencies'
    Write-Host "Starting isolated demo Postgres on 127.0.0.1:$port..."
    Invoke-DemoCompose -ComposeArgs @('up', '-d', 'postgres-demo') -StepName 'start demo Postgres'
    $deadline = [DateTime]::UtcNow.AddSeconds($PostgresTimeoutSeconds)
    $ready = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        & docker compose -p $script:ProjectName -f $script:ComposeFile exec -T postgres-demo pg_isready -U postgres -d ringshield *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        throw "Step 'wait for Postgres readiness' timed out after $PostgresTimeoutSeconds seconds (pg_isready exit code $LASTEXITCODE)."
    }

    $env:RINGSHIELD_MIGRATION_DATABASE_URL = $urls.Admin
    $currentRevision = Get-DemoCurrentRevision -Python $python -AdminUrl $urls.Admin
    if ($currentRevision -eq 'base' -or $currentRevision -eq '0001_platform_schema') {
        Invoke-Checked $python @('-m', 'alembic', '-c', 'platform/alembic.ini', 'upgrade', '0002_role_ownership_force_rls') 'migrate schema through role ownership revision'
        Invoke-PsqlFile (Join-Path $script:RepoRoot 'platform/tests/isolation/provision_migration_role.sql')
    } elseif ($currentRevision -eq '0002_role_ownership_force_rls') {
        Invoke-PsqlFile (Join-Path $script:RepoRoot 'platform/tests/isolation/provision_migration_role.sql')
    }
    $env:RINGSHIELD_MIGRATION_DATABASE_URL = "postgresql+psycopg://ringshield_test_migrator:test-migrator-only@127.0.0.1:${port}/ringshield?options=-c%20role%3Dringshield_owner"
    Invoke-Checked $python @('-m', 'alembic', '-c', 'platform/alembic.ini', 'upgrade', 'head') 'upgrade schema to head'
    Invoke-Checked $python @('-m', 'alembic', '-c', 'platform/alembic.ini', 'check') 'check migrated schema'
    Invoke-PsqlFile (Join-Path $script:RepoRoot 'platform/db/roles.sql')
    Invoke-PsqlFile (Join-Path $script:RepoRoot 'platform/tests/isolation/provision_test_roles.sql')
    Assert-AppRoleIsRestricted -Python $python -AdminUrl $urls.Admin

    $credentials = Get-DemoCredentials
    $demoUserTenants = $Tenants
    if ($ResetPasswords) {
        $credentials = Reset-DemoCredentials $credentials
        $demoUserTenants = Get-DemoCredentialTenants $credentials
    }
    $env:RINGSHIELD_DATABASE_URL = $urls.App
    $env:RINGSHIELD_PLATFORM_CONFIG = 'platform/config.yaml'
    $seedArguments = @('platform/jobs/seed_tenants.py', '--account-map', $accountMap)
    foreach ($tenantId in $Tenants) { $seedArguments += @('--loaded-bank', [string]$tenantId) }
    Invoke-Checked $python $seedArguments 'seed tenants and counterparty registry'
    Write-DemoUsers -Python $python -AdminUrl $urls.Admin -Credentials $credentials `
        -SelectedTenants $demoUserTenants -AuditPasswordReset:$ResetPasswords
    if ($ResetPasswords) {
        Write-Host "Demo passwords reset. Credentials file: $script:CredentialsPath"
    }

    $env:RINGSHIELD_LOADER_DATABASE_URL = $urls.Loader
    $env:RINGSHIELD_DATABASE_URL = $urls.App
    $env:RINGSHIELD_PLATFORM_CONFIG = 'platform/config.yaml'
    $edgeCounts = @{}
    $ringCounts = @{}
    foreach ($tenantId in $Tenants) {
        $edgeFile = Join-Path $validated.EdgeIdsDir "tenant_${tenantId}_edge_ids.parquet"
        $ringFile = Join-Path $validated.RingsDir "tenant_${tenantId}_rings.parquet"
        $edgeCounts[$tenantId] = Get-ParquetRowCount -Python $python -Path $edgeFile
        $ringCounts[$tenantId] = Get-ParquetRowCount -Python $python -Path $ringFile
    }

    Write-Host 'Loading each tenant with an explicit tenant context; cross-bank edges are copied once per visible tenant.'
    foreach ($tenantId in $Tenants) {
        $ringFile = Join-Path $validated.RingsDir "tenant_${tenantId}_rings.parquet"
        Invoke-Checked $python @('platform/jobs/load_contract.py', '--scored-edges', $validated.ScoredEdges,
            '--rings', $ringFile, '--scope', 'tenant', '--tenant-id', [string]$tenantId) "load tenant $tenantId transactions, scores, and rings"
    }
    $explanationCounts = @{}
    foreach ($tenantId in $Tenants) {
        $explanationFile = Join-Path $validated.ExplanationsDir "explanations_${tenantId}_1.parquet"
        $ringsLog = Join-Path $validated.RingsDir "tenant_${tenantId}_rings.parquet.log.json"
        Write-Host "Loading verified explanations for tenant $tenantId..."
        Invoke-Checked $python @('platform/jobs/load_explanations.py', '--explanations', $explanationFile,
            '--run-log', "$explanationFile.log.json", '--rings-log', $ringsLog) "load tenant $tenantId explanations"
        $explanationCounts[$tenantId] = Get-ParquetRowCount -Python $python -Path $explanationFile
        if ($explanationCounts[$tenantId] -ne $ringCounts[$tenantId]) {
            throw "Tenant $tenantId has $($explanationCounts[$tenantId]) explanation rows for $($ringCounts[$tenantId]) rings."
        }
    }

    $expectedEdges = @{ '12' = 20039; '20' = 10315 }
    Write-Host 'Stored tenant row counts:'
    Write-DemoCounts -Python $python -AdminUrl $urls.Admin -SelectedTenants $Tenants `
        -ExpectedEdges $expectedEdges -InputEdgeCounts $edgeCounts -InputRingCounts $ringCounts `
        -InputExplanationCounts $explanationCounts
    foreach ($tenantId in $Tenants) {
        $expected = $expectedEdges[[string]$tenantId]
        Write-Host ("Tenant {0}: visible edge IDs {1}{2}; rings {3}/5; explanation rows loaded {4}." -f `
            $tenantId, $edgeCounts[$tenantId], $(if ($null -ne $expected) { " (expected $expected)" } else { '' }),
            $ringCounts[$tenantId], $explanationCounts[$tenantId])
    }

    Stop-DemoProcesses
    New-Item -ItemType Directory -Path $script:RuntimeDir -Force -ErrorAction Stop | Out-Null
    $script:DemoProcesses = [System.Collections.Generic.List[object]]::new()
    $jwtSecret = if ($credentials.Contains('jwt_secret')) { $credentials.jwt_secret } else { New-DemoPassword }
    if (-not $credentials.Contains('jwt_secret')) {
        Add-Content -LiteralPath $script:CredentialsPath -Value "jwt_secret=$jwtSecret" -Encoding UTF8 -ErrorAction Stop
        $credentials['jwt_secret'] = $jwtSecret
    }
    foreach ($name in @('RINGSHIELD_LOADER_DATABASE_URL', 'RINGSHIELD_DATABASE_ADMIN_URL',
            'RINGSHIELD_DATABASE_ADMIN_PSQL_URL', 'RINGSHIELD_MIGRATION_DATABASE_URL',
            'RINGSHIELD_TEST_ADMIN_URL', 'RINGSHIELD_SIMULATOR_DATABASE_URL',
            'RINGSHIELD_DEMO_ADMIN_URL', 'RINGSHIELD_DEMO_USERS_JSON',
            'RINGSHIELD_DEMO_POSTGRES_PASSWORD', 'RINGSHIELD_XAI_TOKEN')) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
    if ($StartFakeL4) {
        $fakePortFile = Join-Path $script:RuntimeDir 'fake-l4-port.txt'
        Remove-Item -LiteralPath $fakePortFile -Force -ErrorAction SilentlyContinue
        $env:RINGSHIELD_XAI_TOKEN = $script:EffectiveXaiToken
        $fakeOut = Join-Path $script:RuntimeDir 'fake-l4.out.log'
        $fakeErr = Join-Path $script:RuntimeDir 'fake-l4.err.log'
        $fakeProcess = Start-Process -FilePath $python -ArgumentList @('scripts/fake_l4_server.py',
            '--port', '0', '--port-file', ('"{0}"' -f $fakePortFile)) -WorkingDirectory $script:RepoRoot `
            -WindowStyle Hidden -PassThru -RedirectStandardOutput $fakeOut -RedirectStandardError $fakeErr `
            -ErrorAction Stop
        Remove-Item Env:RINGSHIELD_XAI_TOKEN -ErrorAction SilentlyContinue
        Save-DemoProcess -Process $fakeProcess -Kind 'fake_l4' -StopFile $null
        $fakePortDeadline = [DateTime]::UtcNow.AddSeconds(10)
        while (-not (Test-Path -LiteralPath $fakePortFile -PathType Leaf) -and [DateTime]::UtcNow -lt $fakePortDeadline) {
            $fakeProcess.Refresh()
            if ($fakeProcess.HasExited) { throw "Step 'start fake L4' failed; inspect $fakeErr." }
            Start-Sleep -Milliseconds 100
        }
        if (-not (Test-Path -LiteralPath $fakePortFile -PathType Leaf)) {
            throw "Step 'start fake L4' timed out; inspect $fakeErr."
        }
        $fakePort = 0
        $fakePortText = (Get-Content -LiteralPath $fakePortFile -Raw -ErrorAction Stop).Trim()
        if (-not [int]::TryParse($fakePortText, [ref]$fakePort) -or $fakePort -lt 1 -or $fakePort -gt 65535) {
            throw "Step 'start fake L4' returned an invalid local port."
        }
        $script:DemoL4Options.Url = "http://127.0.0.1:$fakePort/regenerate"
    }
    $env:RINGSHIELD_WORKER_MODE = 'supervisor'
    if (-not [string]::IsNullOrWhiteSpace($script:DemoL4Options.Url)) {
        $env:RINGSHIELD_L4_REGENERATE_URL = $script:DemoL4Options.Url
    } else {
        Remove-Item Env:RINGSHIELD_L4_REGENERATE_URL -ErrorAction SilentlyContinue
    }
    $env:RINGSHIELD_DATABASE_URL = $urls.App
    $env:RINGSHIELD_AUTH_DATABASE_URL = $urls.Auth
    $env:RINGSHIELD_JWT_SECRET = $credentials.jwt_secret
    $env:RINGSHIELD_TIME_ORIGIN_UTC = $TimeOriginUtc
    $env:RINGSHIELD_PLATFORM_CONFIG = 'platform/config.yaml'
    $env:PYTHON_DOTENV_DISABLED = '1'
    $env:RINGSHIELD_ARTIFACT_DIR = $modelDir
    $apiStdout = Join-Path $script:RuntimeDir 'api.out.log'
    $apiStderr = Join-Path $script:RuntimeDir 'api.err.log'
    $apiProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'api.main:app',
        '--app-dir', 'platform', '--host', '127.0.0.1', '--port', '8000', '--no-access-log') -WorkingDirectory $script:RepoRoot `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $apiStdout -RedirectStandardError $apiStderr `
        -ErrorAction Stop
    Save-DemoProcess -Process $apiProcess -Kind 'api' -StopFile $null
    $apiReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $apiProcess.Refresh()
        if ($apiProcess.HasExited) {
            throw "Step 'start API' failed with exit code $($apiProcess.ExitCode); inspect $apiStderr."
        }
        try {
            $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -eq 200) { $apiReady = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $apiReady) { throw "Step 'wait for API health' timed out; inspect $apiStderr." }

    $stopFile = Join-Path $script:RuntimeDir 'supervisor.stop'
    Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
    foreach ($name in @('RINGSHIELD_DATABASE_URL', 'RINGSHIELD_AUTH_DATABASE_URL',
            'RINGSHIELD_JWT_SECRET', 'RINGSHIELD_DATABASE_ADMIN_URL',
            'RINGSHIELD_DATABASE_ADMIN_PSQL_URL', 'RINGSHIELD_MIGRATION_DATABASE_URL',
            'RINGSHIELD_TEST_ADMIN_URL', 'RINGSHIELD_SIMULATOR_DATABASE_URL')) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
    $env:RINGSHIELD_LOADER_DATABASE_URL = $urls.Loader
    if (-not [string]::IsNullOrWhiteSpace($script:EffectiveXaiToken)) {
        $env:RINGSHIELD_XAI_TOKEN = $script:EffectiveXaiToken
    }
    $supervisorOut = Join-Path $script:RuntimeDir 'supervisor.out.log'
    $supervisorErr = Join-Path $script:RuntimeDir 'supervisor.err.log'
    $supervisorProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'jobs.worker_supervisor',
        '--poll-seconds', '2', '--max-concurrent', '2', '--stop-file', ('"{0}"' -f $stopFile)) `
        -WorkingDirectory (Join-Path $script:RepoRoot 'platform') -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $supervisorOut -RedirectStandardError $supervisorErr -ErrorAction Stop
    Remove-Item Env:RINGSHIELD_LOADER_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:RINGSHIELD_XAI_TOKEN -ErrorAction SilentlyContinue
    Save-DemoProcess -Process $supervisorProcess -Kind 'supervisor' -StopFile $stopFile

    $env:RINGSHIELD_API_URL = 'http://127.0.0.1:8000'
    Remove-Item Env:RINGSHIELD_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:RINGSHIELD_AUTH_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:RINGSHIELD_JWT_SECRET -ErrorAction SilentlyContinue
    Remove-Item Env:RINGSHIELD_WORKER_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:RINGSHIELD_L4_REGENERATE_URL -ErrorAction SilentlyContinue
    $dashboardStdout = Join-Path $script:RuntimeDir 'dashboard.out.log'
    $dashboardStderr = Join-Path $script:RuntimeDir 'dashboard.err.log'
    $dashboardProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'streamlit', 'run',
        'platform/dashboard/app.py', '--server.address', '127.0.0.1', '--server.port', '8501') `
        -WorkingDirectory $script:RepoRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $dashboardStdout -RedirectStandardError $dashboardStderr -ErrorAction Stop
    Save-DemoProcess -Process $dashboardProcess -Kind 'dashboard' -StopFile $null
    $dashboardReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $dashboardProcess.Refresh()
        if ($dashboardProcess.HasExited) {
            throw "Step 'start dashboard' failed with exit code $($dashboardProcess.ExitCode); inspect $dashboardStderr."
        }
        try {
            $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8501' -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -eq 200) { $dashboardReady = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $dashboardReady) { throw "Step 'wait for dashboard readiness' timed out; inspect $dashboardStderr." }

    Write-Host 'Demo services are ready.'
    Write-Host "Time origin: $TimeOriginUtc"
    Write-Host 'API:       http://127.0.0.1:8000'
    Write-Host 'Dashboard: http://127.0.0.1:8501'
    Write-Host "Logins are in $script:CredentialsPath (passwords are not printed)."
    Write-Host 'Stop containers and local servers with: .\scripts\run-demo.ps1 -Down'
    Write-Host 'To remove the database volume and credentials too: .\scripts\run-demo.ps1 -Down -DropVolume'
} catch {
    Write-Error "RingShield demo failed: $($_.Exception.Message)"
    exit 1
} finally {
    Remove-Item Env:RINGSHIELD_DEMO_ADMIN_URL -ErrorAction SilentlyContinue
    Remove-Item Env:RINGSHIELD_DEMO_USERS_JSON -ErrorAction SilentlyContinue
    Remove-Item Env:RINGSHIELD_DEMO_PASSWORD_RESET -ErrorAction SilentlyContinue
    if ($script:LocationPushed) {
        Pop-Location -ErrorAction SilentlyContinue
        $script:LocationPushed = $false
    }
}
