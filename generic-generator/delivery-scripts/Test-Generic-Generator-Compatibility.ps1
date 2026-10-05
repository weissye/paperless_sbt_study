[CmdletBinding()]
param([string]$Root = (Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Get-StudyPython
$generatorRoot = Join-Path $Root 'generic-generator'
$temporaryCases = Join-Path ([IO.Path]::GetTempPath()) ('sbt-transport-' + [guid]::NewGuid().ToString('N') + '.json')
Push-Location $generatorRoot
$savedPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & $python.Exe @($python.Prefix) -m unittest discover -s tests -v
    $testExit = $LASTEXITCODE
    if ($testExit -ne 0) { throw 'Generic generator compatibility tests failed.' }
    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node) {
        & $python.Exe @($python.Prefix) 'tests/export_transport_cases.py' $temporaryCases
        if ($LASTEXITCODE -ne 0) { throw 'Transport comparison export failed.' }
        & $node.Source 'tests/check_transport_equivalence.js' $temporaryCases
        if ($LASTEXITCODE -ne 0) { throw 'Transport callback comparison failed.' }
    } else {
        Write-Host 'Node was not found. Optional callback comparison was skipped.'
    }
    Write-Host 'GENERIC_GENERATOR_COMPATIBILITY_PASS'
    Write-Host 'Static generation checks only. No server requests were sent.'
} finally {
    $ErrorActionPreference = $savedPreference
    Pop-Location
    if (Test-Path -LiteralPath $temporaryCases) { Remove-Item -LiteralPath $temporaryCases -Force }
}
