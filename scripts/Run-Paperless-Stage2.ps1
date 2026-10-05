[CmdletBinding()]
param([string]$Root=(Split-Path -Parent $PSScriptRoot),[string]$Container,[switch]$SampleOnly)
$ErrorActionPreference='Stop'
& {
    $Root=(Resolve-Path -LiteralPath $Root).Path
    foreach ($test in @('test_paperless_stage1.py','test_stage1_bridge.py','test_paperless_stage2.py')) {
        & py -3 -B (Join-Path $Root "tools/$test")
        if ($LASTEXITCODE -ne 0) { throw "Local validation failed: $test. Campaign was not started." }
    }
    $arguments=@('-3','-B',(Join-Path $Root 'tools/paperless_stage1.py'),'--root',$Root,'--profile','profiles/paperless-stage2-runtime.json','--label','stage2')
    if ($Container) { $arguments+=@('--container',$Container) }
    if ($SampleOnly) { $arguments+='--sample-only' } else {
        docker info --format '{{.ServerVersion}}'
        if ($LASTEXITCODE -ne 0) { throw 'Docker engine is unavailable.' }
        Write-Host 'Stage2: one ordinary user; six fresh owned-resource schedules; no deletion or automatic retry.'
    }
    & py @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Stage2 stopped. Preserve the printed campaign.zip before any further run.' }
}
