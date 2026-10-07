[CmdletBinding()]
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Container,
    [switch]$SampleOnly
)
$ErrorActionPreference = 'Stop'
& {
    $Root = (Resolve-Path -LiteralPath $Root).Path
    $runner = Join-Path $Root 'tools/paperless_stage1.py'
    if (-not (Test-Path -LiteralPath $runner)) { throw "Runner not found: $runner" }
    $test = Join-Path $Root 'tools/test_paperless_stage1.py'
    Write-Host 'Checking the bounded runner with a local HTTP fixture. No Paperless requests are sent.'
    & py -3 -B $test
    if ($LASTEXITCODE -ne 0) { throw 'Local stage1 regression checks failed. Paperless campaign was not started.' }
    $arguments = @('-3', '-B', $runner, '--root', $Root)
    if ($Container) { $arguments += @('--container', $Container) }
    if ($SampleOnly) {
        $arguments += '--sample-only'
    } else {
        docker info --format '{{.ServerVersion}}'
        if ($LASTEXITCODE -ne 0) { throw 'Docker engine is unavailable.' }
        Write-Host 'Creating one ordinary fixture user, then up to six owned-resource schedules.'
        Write-Host 'All fixture users, documents, tags and document types are retained. Stop at the first incomplete or candidate run.'
    }
    & py @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Stage1 did not complete. Preserve the printed campaign.zip; do not automatically rerun.' }
}
