[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Username,
    [ValidateRange(1, 5)][int]$Runs = 3,
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$BaseUrl = 'http://127.0.0.1:9925',
    [string]$ReviewZip = (Join-Path $env:USERPROFILE 'Downloads\generic_relationship_cycle_campaign_review.zip')
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Get-StudyPython
$studyRoot = [IO.Path]::GetFullPath($Root)
$generatorRoot = Join-Path $studyRoot 'generic-generator'
$campaignRoot = Join-Path $studyRoot ('runs\relationship-cycle-campaign-' + [guid]::NewGuid().ToString('N').Substring(0, 12))
New-Item -ItemType Directory -Path $campaignRoot -Force | Out-Null
$projects = @()
$manifest = Join-Path $campaignRoot 'campaign-manifest.json'
Write-Host ('Expanded campaign: {0} independent runs, 35 owned resources per run, cycles 2 through 5.' -f $Runs)
Write-Host 'Each run samples one native random schedule. Actual order diversity is measured, not assumed.'
Write-Host 'The password prompt appears once per live run. No automatic reset or cleanup is performed.'
& (Join-Path $PSScriptRoot 'Test-Generic-Generator-Compatibility.ps1') -Root $studyRoot
$failure = $null
$collectionCode = 1
try {
    for ($index = 1; $index -le $Runs; $index++) {
        Write-Host ('Campaign run {0}/{1}' -f $index, $Runs)
        $provengoRoot = Join-Path $studyRoot 'provengo'
        $existing = @(Get-ChildItem -LiteralPath $provengoRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
        & (Join-Path $PSScriptRoot 'Prepare-Generic-Provengo-Model.ps1') `
            -Root $studyRoot -OpenApi (Join-Path $generatorRoot 'compatibility\contracts\mealie.json') `
            -Name 'mealie' -BaseUrl $BaseUrl -Seed (200 + $index) -ResourceMaps -CompileRelationships `
            -RelationshipProfile (Join-Path $generatorRoot 'profiles\mealie-relational-cycle-expansion.json') `
            -RelationshipRuntime (Join-Path $generatorRoot 'profiles\mealie-relational-runtime.json') `
            -ReviewZip (Join-Path $campaignRoot ('generation-' + $index + '.zip'))
        $created = @(Get-ChildItem -LiteralPath $provengoRoot -Directory | Where-Object {
            $_.FullName -notin $existing -and (Test-Path -LiteralPath (Join-Path $_.FullName 'relationship_compilation.json'))
        })
        if ($created.Count -ne 1) { throw 'Could not identify the newly generated campaign project.' }
        $project = $created[0].FullName
        $projects += $project
        [ordered]@{ expected_runs = $Runs; projects = @($projects); generation_seeds = @(201..(200 + $projects.Count)); native_sampler_seed_pinned = $false } |
            ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifest -Encoding UTF8
        & (Join-Path $PSScriptRoot 'Sample-Generic-Relationship-Model.ps1') -Root $studyRoot -Project $project -Size 1 `
            -ReviewZip (Join-Path $campaignRoot ('sampling-' + $index + '.zip'))
        & (Join-Path $PSScriptRoot 'Invoke-Generic-Relationship-Scenario.ps1') -Root $studyRoot -Project $project -Username $Username -SampleId 1 `
            -ReviewZip (Join-Path $campaignRoot ('live-' + $index + '.zip'))
    }
} catch {
    $failure = $_
} finally {
    if (-not (Test-Path -LiteralPath $manifest)) {
        [ordered]@{ expected_runs = $Runs; projects = @($projects) } | ConvertTo-Json -Depth 8 |
            Set-Content -LiteralPath $manifest -Encoding UTF8
    }
    & $python.Exe @($python.Prefix) (Join-Path $generatorRoot 'tools\relationship_campaign.py') --manifest $manifest --review-zip $ReviewZip
    $collectionCode = $LASTEXITCODE
}
if ($failure) { throw $failure }
if ($collectionCode -ne 0) { throw 'Expanded campaign was not accepted. Inspect the campaign review ZIP.' }
Write-Host ('Campaign evidence: ' + $campaignRoot)
