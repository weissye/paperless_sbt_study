[CmdletBinding()]
param([string]$Root=(Split-Path -Parent $PSScriptRoot),[string]$Container,[switch]$SampleOnly)
$ErrorActionPreference='Stop'
& {
    $Root=(Resolve-Path -LiteralPath $Root).Path
    foreach ($test in @('test_paperless_stage1.py','test_stage1_bridge.py','test_paperless_stage2.py','test_paperless_stage3.py','test_paperless_stage4.py')) {
        & py -3 -B (Join-Path $Root "tools/$test")
        if ($LASTEXITCODE -ne 0) { throw "Local validation failed: $test. Campaign was not started." }
    }
    & py -3 -B (Join-Path $Root 'tools/verify_stage3_complete.py') $Root
    if ($LASTEXITCODE -ne 0) { throw 'Completed Stage3 evidence was not verified. Stage4 was not started.' }
    $arguments=@('-3','-B',(Join-Path $Root 'tools/paperless_stage1.py'),'--root',$Root,'--profile','profiles/paperless-stage4-runtime.json','--label','stage4')
    if ($Container) { $arguments+=@('--container',$Container) }
    if ($SampleOnly) { $arguments+='--sample-only' } else {
        docker info --format '{{.ServerVersion}}'
        if ($LASTEXITCODE -ne 0) { throw 'Docker engine is unavailable.' }
        Write-Host 'Stage4: one ordinary user; six fresh schedules. Bulk add/remove; documents A/B selected, C unselected. No resources are deleted.'
        Write-Host 'Documents, users, unrelated resources and evidence are retained. No automatic cleanup or retry.'
    }
    & py @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Stage4 stopped. Preserve the printed campaign.zip before any further run.' }
}
