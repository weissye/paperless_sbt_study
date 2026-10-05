[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Username,
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$BaseUrl = 'http://127.0.0.1:9925',
    [string]$Campaign
)
$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath($Root)
if (-not $Campaign) {
    $Campaign = Join-Path $Root 'evidence\route-identity-20261004-231327\campaign-original.zip'
}
if (-not (Test-Path -LiteralPath $Campaign)) {
    throw "Preserved campaign not found: $Campaign"
}
$hashFile = Join-Path (Split-Path $Campaign -Parent) 'SHA256.txt'
if (-not (Test-Path -LiteralPath $hashFile)) { throw 'Original campaign SHA256 file is missing.' }
$expectedHash = ([IO.File]::ReadAllText($hashFile).Trim() -split '\s+')[0]
if ($expectedHash -notmatch '^[0-9A-Fa-f]{64}$' -or (Get-FileHash -LiteralPath $Campaign -Algorithm SHA256).Hash -ne $expectedHash) {
    throw 'Original campaign SHA256 verification failed. No requests were sent.'
}
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Get-StudyPython
$previousUsername = $env:SBT_REL_USERNAME
$previousPassword = $env:SBT_REL_PASSWORD
$previousOptions = $env:JAVA_TOOL_OPTIONS
$password = Read-Host 'API password (hidden)' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
try {
    $env:SBT_REL_USERNAME = $Username
    $env:SBT_REL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $env:JAVA_TOOL_OPTIONS = ("$previousOptions -Xmx512m").Trim()
    Write-Host 'Reading archived resource identities. No resource mutations will be sent.'
    Write-Host 'Missing resources on a different server are not classified as bugs.'
    & $python.Exe @($python.Prefix) -B (Join-Path $Root 'generic-generator\tools\audit_route_state.py') `
        --root $Root --campaign $Campaign --expected-sha256 $expectedHash --base-url $BaseUrl
    if ($LASTEXITCODE -ne 0) {
        throw 'Read-only audit did not complete. Inspect its review ZIP; do not rerun the mutation campaign.'
    }
} finally {
    $env:SBT_REL_USERNAME = $previousUsername
    $env:SBT_REL_PASSWORD = $previousPassword
    $env:JAVA_TOOL_OPTIONS = $previousOptions
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $password.Dispose()
}
