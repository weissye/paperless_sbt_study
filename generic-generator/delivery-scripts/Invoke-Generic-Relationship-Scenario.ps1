[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [Parameter(Mandatory = $true)][string]$Username,
    [ValidateRange(1, 20)][int]$SampleId = 1,
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$ReviewZip = (Join-Path $env:USERPROFILE 'Downloads\generic_relationship_live_review.zip')
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Get-StudyPython
$projectPath = (Resolve-Path -LiteralPath $Project).Path
$password = Read-Host 'API password (hidden)' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
$previousUsername = $env:SBT_REL_USERNAME
$previousPassword = $env:SBT_REL_PASSWORD
try {
    $env:SBT_REL_USERNAME = $Username
    $env:SBT_REL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    Write-Host 'Replaying one generated native schedule. New owned resources will be created.'
    & $python.Exe @($python.Prefix) (Join-Path $Root 'generic-generator\tools\relationship_execution.py') run --project $projectPath --sample-id $SampleId --review-zip $ReviewZip
    if ($LASTEXITCODE -ne 0) { throw 'Native live replay was not accepted. Inspect the review ZIP.' }
} finally {
    $env:SBT_REL_USERNAME = $previousUsername
    $env:SBT_REL_PASSWORD = $previousPassword
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $password.Dispose()
}
