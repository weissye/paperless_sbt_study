[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [ValidateRange(1, 20)][int]$Size = 3,
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$ReviewZip = (Join-Path $env:USERPROFILE 'Downloads\generic_relationship_sampling_review.zip')
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Get-StudyPython
$projectPath = (Resolve-Path -LiteralPath $Project).Path
Write-Host 'Sampling compiled relationship actors. No server requests are sent.'
& $python.Exe @($python.Prefix) (Join-Path $Root 'generic-generator\tools\relationship_execution.py') sample --project $projectPath --size $Size --review-zip $ReviewZip
if ($LASTEXITCODE -ne 0) { throw 'Native symbolic sampling was not accepted. Inspect the review ZIP.' }
