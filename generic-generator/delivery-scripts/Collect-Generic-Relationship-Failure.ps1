param(
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$Container = 'mealie-sbt-study-mealie-1',
    [string]$Since = '2026-10-01T13:32:40Z',
    [string]$Until = '2026-10-01T13:33:30Z',
    [string]$ReviewZip = "$env:USERPROFILE\Downloads\generic_relationship_failure_review.zip"
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$tool = Join-Path $root 'generic-generator\tools\collect_relationship_failure.py'
Write-Host 'Collecting evidence from the existing failed run. No API requests are sent.'
& python $tool --project $Project --output $ReviewZip --container $Container --since $Since --until $Until
if ($LASTEXITCODE -ne 0) { throw 'Read-only evidence collection failed.' }
