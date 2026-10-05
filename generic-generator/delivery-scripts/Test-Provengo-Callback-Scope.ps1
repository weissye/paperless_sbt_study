[CmdletBinding()]
param(
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$BaseUrl = 'http://127.0.0.1:9925'
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Get-StudyPython
$review = Join-Path $env:USERPROFILE ('Downloads\provengo_callback_scope_review_' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.zip')
Invoke-WebRequest -Uri ($BaseUrl.TrimEnd('/') + '/openapi.json') -UseBasicParsing -TimeoutSec 15 | Out-Null
$savedOptions = $env:JAVA_TOOL_OPTIONS
try {
    $env:JAVA_TOOL_OPTIONS = ("$savedOptions -Xmx1g").Trim()
    & $python.Exe @($python.Prefix) (Join-Path $Root 'generic-generator\tools\callback_scope_probe.py') `
        --root $Root --base-url $BaseUrl --review-zip $review
    if ($LASTEXITCODE -ne 0) {
        throw "Native callback scope probe was not accepted. Upload $review. Do not rerun the relationship pilot."
    }
} finally {
    $env:JAVA_TOOL_OPTIONS = $savedOptions
}
