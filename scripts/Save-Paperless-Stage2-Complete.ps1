[CmdletBinding()]
param([string]$Root = (Split-Path -Parent $PSScriptRoot), [switch]$Push)
$ErrorActionPreference = 'Stop'
& {
    Set-Location $Root
    $manifestPath = Join-Path $Root 'validation/paperless-stage2-complete-release.json'
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
            try { $actual = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized))).Replace('-', '').ToLowerInvariant() }
            finally { $sha.Dispose() }
        }
        if ($actual -ne $expected) { throw "Release file differs: $path. Git was not changed." }
    }
    & py -3 -B (Join-Path $Root 'tools/verify_stage2_complete.py') $Root
    if ($LASTEXITCODE -ne 0) { throw 'Stage2 evidence verification failed. Git was not changed.' }
    $paths += 'validation/paperless-stage2-complete-release.json'
    git add -f -- @paths
    if ($LASTEXITCODE -ne 0) { throw 'Evidence staging failed.' }
    git diff --cached --quiet -- @paths
    $diffCode = $LASTEXITCODE
    if ($diffCode -eq 1) {
        git commit --only -m 'Preserve complete Paperless hierarchy campaign and plan linked deletion' -- @paths
        if ($LASTEXITCODE -ne 0) { throw 'Commit failed. Push was not started.' }
    } elseif ($diffCode -ne 0) { throw 'Staged evidence check failed.' }
    if ($Push) {
        git push origin HEAD
        if ($LASTEXITCODE -ne 0) { throw 'Push failed. Local commit was preserved.' }
        git fetch origin
        if ($LASTEXITCODE -ne 0) { throw 'Remote verification fetch failed.' }
        $branch = git symbolic-ref --short HEAD
        if ($LASTEXITCODE -ne 0) { throw 'Cannot determine current branch.' }
        $head = git rev-parse HEAD
        if ($LASTEXITCODE -ne 0) { throw 'Cannot determine local commit.' }
        $remote = git rev-parse "refs/remotes/origin/$branch"
        if ($LASTEXITCODE -ne 0 -or $head -ne $remote) { throw 'Remote head was not verified.' }
        Write-Host "STAGE2_COMPLETE_EVIDENCE_PUSH_VERIFIED: $head"
    }
    git log -1 --oneline
}
