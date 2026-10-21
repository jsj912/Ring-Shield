$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$demoScript = Join-Path $repoRoot 'scripts/run-demo.ps1'
. $demoScript -DefinitionsOnly

$automaticVariableNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
@(
    'args', 'ConfirmPreference', 'ConsoleFileName', 'DebugPreference', 'Error', 'ErrorActionPreference',
    'Event', 'EventArgs', 'EventSubscriber', 'ExecutionContext', 'false', 'foreach', 'HOME', 'Host',
    'InformationPreference', 'Input', 'IsCoreCLR', 'IsLinux', 'IsMacOS', 'IsWindows', 'LASTEXITCODE',
    'Matches', 'MyInvocation', 'NestedPromptLevel', 'OFS', 'OutputEncoding', 'PID', 'PROFILE',
    'ProgressPreference', 'PSBoundParameters', 'PSCmdlet', 'PSCommandPath', 'PSCulture',
    'PSDefaultParameterValues', 'PSEdition', 'PSEmailServer', 'PSErrorView', 'PSHOME', 'PSItem',
    'PSNativeCommandArgumentPassing', 'PSNativeCommandUseErrorActionPreference', 'PSScriptRoot',
    'PSSenderInfo', 'PSStyle', 'PSUICulture', 'PSVersionTable', 'PWD', 'Sender', 'ShellId',
    'StackTrace', 'switch', 'This', 'true', 'VerbosePreference', 'WarningPreference',
    'WhatIfPreference', '_'
) | ForEach-Object { [void]$automaticVariableNames.Add($_) }
$parser = [System.Management.Automation.Language.Parser]
$syntaxFiles = @($demoScript, $PSCommandPath)
foreach ($syntaxFile in $syntaxFiles) {
    $tokens = $null
    $parseErrors = $null
    $scriptAst = $parser::ParseFile($syntaxFile, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count -gt 0) {
        throw "PowerShell syntax parse failed for $syntaxFile`: $($parseErrors[0].Message)"
    }
    $assignments = $scriptAst.FindAll({ param($astNode)
        $astNode -is [System.Management.Automation.Language.AssignmentStatementAst]
    }, $true)
    foreach ($assignment in $assignments) {
        $targetVariables = @()
        if ($assignment.Left -is [System.Management.Automation.Language.VariableExpressionAst]) {
            $targetVariables += $assignment.Left
        }
        $targetVariables += $assignment.Left.FindAll({ param($astNode)
            $astNode -is [System.Management.Automation.Language.VariableExpressionAst]
        }, $true)
        foreach ($targetVariable in $targetVariables) {
            $targetName = $targetVariable.VariablePath.UserPath
            if ($automaticVariableNames.Contains($targetName)) {
                throw "Assignment targets PowerShell automatic/preference variable '$targetName' in $syntaxFile`: $($assignment.Extent.Text)"
            }
        }
    }
}
$passed = 1

try {
    ConvertFrom-ParquetRowCountOutput -Output @() -ExitCode 0 -Path 'empty-output.parquet' | Out-Null
    throw 'An empty parquet row-count result was unexpectedly accepted.'
} catch {
    if ($_.Exception.Message -notmatch 'command returned empty output') { throw }
    $passed++
}

try {
    ConvertFrom-ParquetRowCountOutput -Output @('metadata read failed') -ExitCode 1 `
        -Path 'broken.parquet' | Out-Null
    throw 'A failed parquet row-count command was unexpectedly accepted.'
} catch {
    if ($_.Exception.Message -notmatch 'metadata read failed') { throw }
    $passed++
}

$demoSource = Get-Content -LiteralPath $demoScript -Raw -Encoding UTF8 -ErrorAction Stop
if ($demoSource -notmatch '(?m)^\s*\[switch\]\$ResetPasswords\s*,?\s*$') {
    throw 'run-demo.ps1 does not define the -ResetPasswords switch.'
}
if ($demoSource -notmatch '\$ResetPasswords\s+-and\s+\$Down') {
    throw 'run-demo.ps1 does not reject -ResetPasswords combined with -Down.'
}
$passwordOutput = [regex]::Matches(
    $demoSource,
    '(?im)^\s*(Write-Host|Write-Output|Write-Information)\b[^\r\n]*\$(?:\w*password\w*|credentials\.(?:admin|tenant_\w+)_password)'
)
if ($passwordOutput.Count -gt 0) {
    throw 'run-demo.ps1 contains an output command that interpolates a password value.'
}
try {
    & $demoScript -ResetPasswords -Down
    throw '-ResetPasswords -Down was unexpectedly accepted.'
} catch {
    if ($_.Exception.Message -notmatch 'cannot be combined with -Down') { throw }
}
$passed++

try {
    Assert-TimeOriginUtc ''
    throw 'Missing TimeOriginUtc was unexpectedly accepted.'
} catch {
    if ($_.Exception.Message -notmatch '-TimeOriginUtc is required.*first transaction day 00:00 UTC minus 10 seconds') { throw }
    $passed++
}

try {
    Assert-TimeOriginUtc '2022-08-31T23:59:50'
    throw 'TimeOriginUtc without a UTC offset was unexpectedly accepted.'
} catch {
    if ($_.Exception.Message -notmatch 'ISO-8601 instant with a UTC offset or Z') { throw }
    $passed++
}

Assert-TimeOriginUtc '2022-08-31T23:59:50Z'
Assert-TimeOriginUtc '2022-08-31T23:59:50+00:00'

$scratch = Join-Path ([System.IO.Path]::GetTempPath()) ("ringshield-demo-validation-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $scratch -Force -ErrorAction Stop | Out-Null
try {
    $rings = Join-Path $scratch 'rings'
    $edges = Join-Path $scratch 'edge-ids'
    $explanations = Join-Path $scratch 'explanations'
    foreach ($directory in @($rings, $edges, $explanations)) {
        New-Item -ItemType Directory -Path $directory -Force -ErrorAction Stop | Out-Null
    }
    $scores = Join-Path $scratch 'scored.parquet'
    Set-Content -LiteralPath $scores -Value 'synthetic' -Encoding UTF8 -ErrorAction Stop
    Set-Content -LiteralPath "$scores.log.json" -Value '{"split":"test"}' -Encoding UTF8 -ErrorAction Stop
    foreach ($tenant in @(12, 20)) {
        Set-Content -LiteralPath (Join-Path $rings "tenant_${tenant}_rings.parquet") -Value 'synthetic' -Encoding UTF8 -ErrorAction Stop
        Set-Content -LiteralPath (Join-Path $rings "tenant_${tenant}_rings.parquet.log.json") `
            -Value '{"split":"test","tenant_rule":"explicit tenant_id=12","edge_subset":"visible.parquet"}' -Encoding UTF8 -ErrorAction Stop
        Set-Content -LiteralPath (Join-Path $edges "tenant_${tenant}_edge_ids.parquet") -Value 'synthetic' -Encoding UTF8 -ErrorAction Stop
        Set-Content -LiteralPath (Join-Path $explanations "explanations_${tenant}_1.parquet") -Value 'synthetic' -Encoding UTF8 -ErrorAction Stop
        Set-Content -LiteralPath (Join-Path $explanations "explanations_${tenant}_1.parquet.log.json") `
            -Value '{"scope":"tenant","tenant_id":12,"feature_scope":"tenant_view"}' -Encoding UTF8 -ErrorAction Stop
    }

    $valid = Assert-DemoInputs -SelectedTenants @(12, 20) -RingFolder $rings `
        -EdgeFolder $edges -ScoreFile $scores -ExplanationFolder $explanations
    if ($valid.Inputs.Count -ne 7) { throw 'Valid input set returned an unexpected file count.' }

    $powerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
    $fileModeOutput = & $powerShellExe -NoProfile -File $demoScript -Tenants '12,20' `
        -ValidateOnly -TimeOriginUtc '2022-08-31T23:59:50Z' -RingsDir $rings `
        -EdgeIdsDir $edges -ScoredEdges $scores -ExplanationsDir $explanations 2>&1
    $fileModeText = $fileModeOutput | Out-String
    if ($LASTEXITCODE -ne 0) { throw "powershell.exe -File rejected -Tenants 12,20: $fileModeText" }
    if ($fileModeText -notmatch 'tenant 12 rings' -or $fileModeText -notmatch 'tenant 20 rings' -or
        $fileModeText -match 'tenant 1220') {
        throw "powershell.exe -File did not normalize tenants 12 and 20 independently: $fileModeText"
    }
    $passed++

    foreach ($invalidTenantInput in @(
        [pscustomobject]@{ Value = '12,nope'; Error = "Invalid -Tenants token 'nope'" },
        [pscustomobject]@{ Value = '12,12'; Error = "Duplicate -Tenants token '12'" }
    )) {
        $invalidOutput = & $powerShellExe -NoProfile -File $demoScript `
            -Tenants $invalidTenantInput.Value -ValidateOnly 2>&1
        $invalidText = $invalidOutput | Out-String
        if ($LASTEXITCODE -eq 0 -or $invalidText -notmatch [regex]::Escape($invalidTenantInput.Error)) {
            throw "powershell.exe -File did not reject tenant input '$($invalidTenantInput.Value)' clearly: $invalidText"
        }
        $passed++
    }

    & $demoScript -ValidateOnly -Tenants @(12, 20) -TimeOriginUtc '2022-08-31T23:59:50Z' -RingsDir $rings `
        -EdgeIdsDir $edges -ScoredEdges $scores -ExplanationsDir $explanations | Out-Null
    $passed++

    try {
        Assert-DemoInputs -SelectedTenants @(12, 20) -RingFolder '' `
            -EdgeFolder $edges -ScoreFile $scores -ExplanationFolder $explanations | Out-Null
        throw 'Missing RingsDir was unexpectedly accepted.'
    } catch {
        if ($_.Exception.Message -notmatch 'Missing required parameter -RingsDir') { throw }
        $passed++
    }

    $unsafe = Join-Path $scratch 'ground_truth'
    try {
        Assert-DemoInputs -SelectedTenants @(12) -RingFolder $unsafe `
            -EdgeFolder $edges -ScoreFile $scores -ExplanationFolder $explanations | Out-Null
        throw 'Ground-truth input path was unexpectedly accepted.'
    } catch {
        if ($_.Exception.Message -notmatch 'Refusing label/ground-truth input path') { throw }
        $passed++
    }

    $labelFile = Join-Path $scratch 'labels_private.parquet'
    Set-Content -LiteralPath $labelFile -Value 'synthetic' -Encoding UTF8 -ErrorAction Stop
    Set-Content -LiteralPath "$labelFile.log.json" -Value '{"split":"test"}' -Encoding UTF8 -ErrorAction Stop
    try {
        Assert-DemoInputs -SelectedTenants @(12) -RingFolder $rings `
            -EdgeFolder $edges -ScoreFile $labelFile -ExplanationFolder $explanations | Out-Null
        throw 'Label-prefixed input path was unexpectedly accepted.'
    } catch {
        if ($_.Exception.Message -notmatch 'Refusing label/ground-truth input path') { throw }
        $passed++
    }

    try {
        Assert-DemoInputs -SelectedTenants @(0) -RingFolder $rings `
            -EdgeFolder $edges -ScoreFile $scores -ExplanationFolder $explanations | Out-Null
        throw 'Non-positive tenant ID was unexpectedly accepted.'
    } catch {
        if ($_.Exception.Message -notmatch 'positive bank IDs') { throw }
        $passed++
    }
    Write-Host "run-demo validation checks passed: $passed"
} finally {
    Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
}
