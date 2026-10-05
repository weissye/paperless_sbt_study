[CmdletBinding()]
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Username = 'research_admin',
    [switch]$SampleOnly
)
$ErrorActionPreference = 'Stop'
$runner = Join-Path $Root 'tools\run_native_smoke.py'
if (-not (Test-Path -LiteralPath $runner)) { throw "Runner not found: $runner" }
$arguments = @('-3', '-B', $runner, '--root', $Root, '--username', $Username)
if ($SampleOnly) { $arguments += '--sample-only' }
& py @arguments
if ($LASTEXITCODE -ne 0) { throw 'Paperless native pilot was not accepted. Inspect the printed review directory.' }
