$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$demoScript = Join-Path $repoRoot 'scripts/run-demo.ps1'
. $demoScript -DefinitionsOnly

$scratch = Join-Path ([System.IO.Path]::GetTempPath()) ("ringshield-demo-validation-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $scratch -Force | Out-Null
$passed = 0
try {
    $rings = Join-Path $scratch 'rings'
    $edges = Join-Path $scratch 'edge-ids'
    $explanations = Join-Path $scratch 'explanations'
    foreach ($directory in @($rings, $edges, $explanations)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $scores = Join-Path $scratch 'scored.parquet'
    Set-Content -LiteralPath $scores -Value 'synthetic' -Encoding UTF8
    Set-Content -LiteralPath "$scores.log.json" -Value '{"split":"test"}' -Encoding UTF8
    foreach ($tenant in @(12, 20)) {
        Set-Content -LiteralPath (Join-Path $rings "tenant_${tenant}_rings.parquet") -Value 'synthetic' -Encoding UTF8
        Set-Content -LiteralPath (Join-Path $rings "tenant_${tenant}_rings.parquet.log.json") `
            -Value '{"split":"test","tenant_rule":"explicit tenant_id=12","edge_subset":"visible.parquet"}' -Encoding UTF8
        Set-Content -LiteralPath (Join-Path $edges "tenant_${tenant}_edge_ids.parquet") -Value 'synthetic' -Encoding UTF8
        Set-Content -LiteralPath (Join-Path $explanations "explanations_${tenant}_1.parquet") -Value 'synthetic' -Encoding UTF8
        Set-Content -LiteralPath (Join-Path $explanations "explanations_${tenant}_1.parquet.log.json") `
            -Value '{"scope":"tenant","tenant_id":12,"feature_scope":"tenant_view"}' -Encoding UTF8
    }

    $valid = Assert-DemoInputs -SelectedTenants @(12, 20) -RingFolder $rings `
        -EdgeFolder $edges -ScoreFile $scores -ExplanationFolder $explanations
    if ($valid.Inputs.Count -ne 7) { throw 'Valid input set returned an unexpected file count.' }
    & $demoScript -ValidateOnly -Tenants @(12, 20) -RingsDir $rings `
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
    Set-Content -LiteralPath $labelFile -Value 'synthetic' -Encoding UTF8
    Set-Content -LiteralPath "$labelFile.log.json" -Value '{"split":"test"}' -Encoding UTF8
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
