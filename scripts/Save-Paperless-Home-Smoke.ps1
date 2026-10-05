param([string]$Root = (Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference = 'Stop'
& {
    Set-Location $Root
    $archive = Join-Path $Root 'evidence/native-smoke-home-20261005-170028/live-review-original.zip'
    $qualification = Get-Content -LiteralPath (Join-Path $Root 'evidence/native-smoke-home-20261005-170028/qualification.json') -Raw | ConvertFrom-Json
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $qualification.archive_sha256) {
        throw 'Evidence checksum mismatch. Git was not changed.'
    }
    $contract = Join-Path $Root 'model/paperless-openapi.json'
    $expected = '7840d7816133c13fdeb43e1cd9a3013c7fff886538f5612bff3d0b42b2119d0c'
    if ((Get-FileHash -LiteralPath $contract -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw 'Pinned contract mismatch. Git was not changed.'
    }
    git rev-parse --show-toplevel | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Project is not a Git repository.' }
    $attributes = Join-Path $Root '.gitattributes'
    $text = if (Test-Path -LiteralPath $attributes) { [IO.File]::ReadAllText($attributes) } else { '' }
    $rule = 'model/paperless-openapi.json -text'
    if (-not ($text -split '\r?\n' | Where-Object { $_.Trim() -eq $rule })) {
        [IO.File]::WriteAllText($attributes, $text.TrimEnd("`r", "`n") + "`n" + $rule + "`n", [Text.UTF8Encoding]::new($false))
    }
    $paths = @('.gitattributes', 'model/paperless-openapi.json',
        'evidence/native-smoke-home-20261005-170028',
        'profiles/paperless-stage1-test-sets.json', 'docs/PAPERLESS-STAGE1.md',
        'scripts/Save-Paperless-Home-Smoke.ps1')
    git add -f -- @paths
    if ($LASTEXITCODE -ne 0) { throw 'Staging failed.' }
    git diff --cached --stat -- @paths
    if ($LASTEXITCODE -ne 0) { throw 'Staged diff inspection failed.' }
    Write-Host 'HOME_SMOKE_AND_STAGE1_DESIGN_STAGED. No campaign, commit or push was performed.'
}
