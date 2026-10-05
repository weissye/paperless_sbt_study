[CmdletBinding()]
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [switch]$Push
)
$ErrorActionPreference = 'Stop'
& {
    Set-Location $Root
    $manifestPath = Join-Path $Root 'validation/paperless-stage2-release.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $paths = @($manifest.files.PSObject.Properties.Name)
    foreach ($path in $paths) {
        $file = Join-Path $Root $path
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Release file missing: $path" }
        $expected = $manifest.files.PSObject.Properties[$path].Value
        $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected -and [IO.Path]::GetExtension($file) -ne '.zip') {
            $normalized = [IO.File]::ReadAllText($file).Replace("`r`n", "`n")
            $sha = [Security.Cryptography.SHA256]::Create()
            try {
                $actual = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized))).Replace('-', '').ToLowerInvariant()
            } finally { $sha.Dispose() }
        }
        if ($actual -ne $expected) {
            throw "Release file differs: $path. No Git changes were made."
        }
    }
    & py -3 -B (Join-Path $Root 'tools/test_paperless_stage1.py')
    if ($LASTEXITCODE -ne 0) { throw 'Stage1 tests failed. No Git changes were made.' }
    & py -3 -B (Join-Path $Root 'tools/test_stage1_bridge.py')
    if ($LASTEXITCODE -ne 0) { throw 'Bridge checks failed. No Git changes were made.' }
    & py -3 -B (Join-Path $Root 'tools/test_paperless_stage2.py')
    if ($LASTEXITCODE -ne 0) { throw 'Hierarchy checks failed. No Git changes were made.' }
    & py -3 -B (Join-Path $Root 'tools/verify_stage1_complete.py') $Root
    if ($LASTEXITCODE -ne 0) { throw 'Stage1 evidence verification failed. No Git changes were made.' }
    $paths += 'validation/paperless-stage2-release.json'
    git add -f -- @paths
    if ($LASTEXITCODE -ne 0) { throw 'Stage1 staging failed.' }
    git diff --cached --quiet -- @paths
    $diffCode = $LASTEXITCODE
    if ($diffCode -eq 1) {
        git commit --only -m 'Preserve completed Paperless stage1 and add bounded tag hierarchy campaign' -- @paths
        if ($LASTEXITCODE -ne 0) { throw 'Stage1 commit failed.' }
    } elseif ($diffCode -ne 0) { throw 'Stage1 staged diff failed.' }
    if ($Push) {
        git push origin HEAD
        if ($LASTEXITCODE -ne 0) { throw 'Stage1 push failed. Local commit was preserved.' }
    }
    git log -1 --oneline
}
