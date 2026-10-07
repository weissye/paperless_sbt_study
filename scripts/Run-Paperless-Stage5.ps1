[CmdletBinding()]
param([string]$Root=(Split-Path -Parent $PSScriptRoot),[string]$Container,[switch]$SampleOnly)
$ErrorActionPreference='Stop'
$Root=(Resolve-Path -LiteralPath $Root).Path
& py -3 -B (Join-Path $Root 'tools/test_paperless_versions.py')
if ($LASTEXITCODE -ne 0) { throw 'Version adapter tests failed. Live execution was not started.' }
$arguments=@('-3','-B',(Join-Path $Root 'tools/paperless_versions.py'),'--root',$Root)
if ($Container) { $arguments+=@('--container',$Container) }
if ($SampleOnly) { $arguments+='--sample-only' } else {
    docker info --format '{{.ServerVersion}}'
    if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop before the campaign.' }
    Write-Host 'Stage5: entity lifecycles; persistent multi-parent readiness; distinct business schedules.'
    Write-Host 'One ordinary fixture user; four initial documents and one additional file version per fresh set.'
    Write-Host 'The third case deletes its own two non-root versions, shared tag and shared type. Root and control documents are retained.'
}
& py @arguments
if ($LASTEXITCODE -ne 0) { throw 'Stage5 stopped. Preserve the printed campaign.zip; inspect it before retrying.' }
