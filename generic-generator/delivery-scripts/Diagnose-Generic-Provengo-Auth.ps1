[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Username,
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$BaseUrl = 'http://127.0.0.1:9925',
    [string]$OpenApi,
    [string]$ReviewZip = (Join-Path $env:USERPROFILE 'Downloads\generic_auth_diagnostic_review.zip')
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Get-StudyPython
if (-not $OpenApi) { $OpenApi = Join-Path $Root 'generic-generator\compatibility\contracts\mealie.json' }
$password = Read-Host 'API password (hidden)' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
$previousUsername = $env:SBT_REL_USERNAME
$previousPassword = $env:SBT_REL_PASSWORD
try {
    $env:SBT_REL_USERNAME = $Username
    $env:SBT_REL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    & $python.Exe @($python.Prefix) (Join-Path $Root 'generic-generator\tools\diagnose_native_auth.py') --root $Root --openapi $OpenApi --base-url $BaseUrl --review-zip $ReviewZip
    if ($LASTEXITCODE -ne 0) { throw 'Authentication diagnostic did not capture the native request. Inspect the review ZIP.' }
} finally {
    $env:SBT_REL_USERNAME = $previousUsername
    $env:SBT_REL_PASSWORD = $previousPassword
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $password.Dispose()
}
