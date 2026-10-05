[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Username,
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$BaseUrl = 'http://127.0.0.1:9925',
    [switch]$SampleOnly,
    [ValidateRange(1, 20)][int]$SampleSize = 3
)
$ErrorActionPreference = 'Stop'
$studyRoot = [IO.Path]::GetFullPath($Root)
& (Join-Path $PSScriptRoot 'Test-Generic-Generator-Compatibility.ps1') -Root $studyRoot
$provengoRoot = Join-Path $studyRoot 'provengo'
$existing = @(Get-ChildItem -LiteralPath $provengoRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
& (Join-Path $PSScriptRoot 'Prepare-Generic-Provengo-Model.ps1') `
    -Root $studyRoot -OpenApi (Join-Path $studyRoot 'generic-generator\compatibility\contracts\mealie.json') `
    -Name 'mealie' -BaseUrl $BaseUrl -ResourceMaps -CompileRelationships `
    -RelationshipProfile (Join-Path $studyRoot 'generic-generator\profiles\mealie-relational-map-pilot.json') `
    -RelationshipRuntime (Join-Path $studyRoot 'generic-generator\profiles\mealie-relational-runtime.json')
$created = @(Get-ChildItem -LiteralPath $provengoRoot -Directory | Where-Object {
    $_.FullName -notin $existing -and (Test-Path -LiteralPath (Join-Path $_.FullName 'relationship_compilation.json'))
})
if ($created.Count -ne 1) { throw 'Could not identify the single newly generated compiled project.' }
$project = $created[0].FullName
& (Join-Path $PSScriptRoot 'Sample-Generic-Relationship-Model.ps1') -Root $studyRoot -Project $project -Size $SampleSize
if (-not $SampleOnly) {
    & (Join-Path $PSScriptRoot 'Invoke-Generic-Relationship-Scenario.ps1') -Root $studyRoot -Project $project -Username $Username -SampleId 1
}
Write-Host ('Compiled project: ' + $project)
