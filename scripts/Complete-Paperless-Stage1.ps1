[CmdletBinding()]
param([string]$Root = (Split-Path -Parent $PSScriptRoot), [string]$Container)
$ErrorActionPreference = 'Stop'
& {
    $Root = (Resolve-Path -LiteralPath $Root).Path
    $archive = Join-Path $Root 'evidence/stage1-partial-20261005-174618/campaign-original.zip'
    & py -3 -B (Join-Path $Root 'tools/verify_stage1_partial.py') $archive
    if ($LASTEXITCODE -ne 0) { throw 'Prior campaign verification failed. No continuation was started.' }
    & py -3 -B (Join-Path $Root 'tools/test_stage1_bridge.py')
    if ($LASTEXITCODE -ne 0) { throw 'Local bridge checks failed.' }
    & py -3 -B (Join-Path $Root 'tools/test_paperless_stage1.py')
    if ($LASTEXITCODE -ne 0) { throw 'Functional fixture checks failed.' }
    docker info --format '{{.ServerVersion}}'
    if ($LASTEXITCODE -ne 0) { throw 'Docker engine is unavailable.' }
    $arguments = @('-3','-B',(Join-Path $Root 'tools/paperless_stage1.py'),'--root',$Root,'--remaining-from',$archive)
    if ($Container) { $arguments += @('--container',$Container) }
    Write-Host 'Completing three missing schedules with a new ordinary user and fresh resources. Existing evidence and resources are retained.'
    & py @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Continuation stopped. Preserve the printed campaign.zip; do not automatically retry.' }
}
