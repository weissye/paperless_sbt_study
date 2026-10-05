[CmdletBinding()]
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath $Root).Path
$compose = Join-Path $Root 'deployment\compose.home.yml'
$settings = Join-Path $Root 'docker-compose.env'
if (-not (Test-Path -LiteralPath $compose)) { throw "Compose file not found: $compose" }
docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop before installing Paperless.' }
if (-not (Test-Path -LiteralPath $settings)) {
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $secretBytes = New-Object byte[] 48
        $dbBytes = New-Object byte[] 32
        $rng.GetBytes($secretBytes)
        $rng.GetBytes($dbBytes)
        $secret = [Convert]::ToBase64String($secretBytes)
        $dbPassword = [Convert]::ToBase64String($dbBytes)
        $content = "PAPERLESS_SECRET_KEY=$secret`nPAPERLESS_DBPASS=$dbPassword`nPAPERLESS_URL=http://127.0.0.1:9930`nPAPERLESS_TIME_ZONE=Asia/Jerusalem`n"
        [IO.File]::WriteAllText($settings, $content, [Text.UTF8Encoding]::new($false))
    } finally { $rng.Dispose() }
}
foreach ($name in @('consume', 'export')) {
    New-Item -ItemType Directory -Path (Join-Path $Root $name) -Force | Out-Null
}
$composeArgs = @('compose', '--project-directory', $Root, '--env-file', $settings, '-f', $compose, '-p', 'paperless-sbt-study')
& docker @composeArgs config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose configuration failed. Existing data was preserved.' }
& docker @composeArgs pull
if ($LASTEXITCODE -ne 0) { throw 'Image download failed. No reset was performed.' }
& docker @composeArgs up -d
if ($LASTEXITCODE -ne 0) { throw 'Container startup failed. Existing volumes were preserved.' }
$ready = $false
for ($attempt = 1; $attempt -le 120; $attempt++) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9930/api/schema/?format=json' -TimeoutSec 5
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    if (($attempt % 10) -eq 0) { Write-Host 'Waiting for Paperless migrations and startup...' }
    Start-Sleep -Seconds 3
}
& docker @composeArgs ps
if (-not $ready) { throw 'Paperless is not ready yet. Inspect docker compose logs; no data was deleted.' }
Write-Host 'PAPERLESS_HOME_SERVER_READY: http://127.0.0.1:9930'
Write-Host 'On a fresh database, open the page and create research_admin. Then run Run-Paperless-Native-Smoke.ps1.'
