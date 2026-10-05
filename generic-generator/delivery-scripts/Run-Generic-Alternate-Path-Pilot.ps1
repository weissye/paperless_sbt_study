[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Username,
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$BaseUrl = 'http://127.0.0.1:9925'
)
$ErrorActionPreference = 'Stop'
$studyRoot = [IO.Path]::GetFullPath($Root)
if ((Get-PSDrive -Name ([IO.Path]::GetPathRoot($studyRoot).Substring(0,1))).Free -lt 1GB) {
    throw 'At least 1 GiB of free disk space is required.'
}
Invoke-WebRequest -Uri ($BaseUrl.TrimEnd('/') + '/openapi.json') -UseBasicParsing -TimeoutSec 15 | Out-Null
& (Join-Path $PSScriptRoot 'Test-Generic-Generator-Compatibility.ps1') -Root $studyRoot
$generator = Join-Path $studyRoot 'generic-generator'
$projects = Join-Path $studyRoot 'provengo'
$before = @(Get-ChildItem -LiteralPath $projects -Directory | ForEach-Object { $_.FullName })
$review = Join-Path $env:USERPROFILE ('Downloads\mealie-alternate-paths-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $review | Out-Null
& (Join-Path $PSScriptRoot 'Prepare-Generic-Provengo-Model.ps1') `
    -Root $studyRoot -OpenApi (Join-Path $generator 'compatibility\contracts\mealie.json') `
    -Name 'mealie' -BaseUrl $BaseUrl -Seed 205 -ResourceMaps -CompileRelationships `
    -RelationshipProfile (Join-Path $generator 'profiles\mealie-relational-alternate-paths.json') `
    -RelationshipRuntime (Join-Path $generator 'profiles\mealie-relational-compact-runtime.json') `
    -ReviewZip (Join-Path $review 'generation.zip')
$created = @(Get-ChildItem -LiteralPath $projects -Directory | Where-Object {
    $_.FullName -notin $before -and (Test-Path -LiteralPath (Join-Path $_.FullName 'relationship_compilation.json'))
})
if ($created.Count -ne 1) { throw 'Could not identify the new alternate-path project.' }
$project = $created[0].FullName
Write-Host ('Project: ' + $project)
$freeRAM = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB
Write-Host ('Free RAM: {0:N2} GiB' -f $freeRAM)
if ($freeRAM -lt 2) {
    throw 'At least 2 GiB free RAM is required. The generated project is preserved.'
}
$savedOptions = $env:JAVA_TOOL_OPTIONS
try {
    $env:JAVA_TOOL_OPTIONS = ("$savedOptions -Xmx1g").Trim()
    & (Join-Path $PSScriptRoot 'Sample-Generic-Relationship-Model.ps1') `
        -Root $studyRoot -Project $project -Size 1 -ReviewZip (Join-Path $review 'sampling.zip')
    $samples = Get-Item -LiteralPath (Join-Path $project 'relationship-samples.json')
    Write-Host ('Native sample size: {0:N2} MiB' -f ($samples.Length / 1MB))
    if ($samples.Length -gt 128MB) {
        throw 'Compact sample exceeded 128 MiB. Live replay was not started.'
    }
    & (Join-Path $PSScriptRoot 'Invoke-Generic-Relationship-Scenario.ps1') `
        -Root $studyRoot -Project $project -Username $Username -SampleId 1 -ReviewZip (Join-Path $review 'live.zip')
} finally {
    $env:JAVA_TOOL_OPTIONS = $savedOptions
}
Write-Host ('Review folder: ' + $review)
Write-Host 'No reset, deletion or automatic retry was performed. Upload live.zip for review.'
