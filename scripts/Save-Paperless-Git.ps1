[CmdletBinding()]
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Remote = 'https://github.com/weissye/paperless_sbt_study.git',
    [switch]$Push
)
$ErrorActionPreference = 'Stop'
$arguments = @('-3', '-B', (Join-Path $Root 'tools\save_git_study.py'), '--root', $Root, '--remote', $Remote)
if ($Push) { $arguments += '--push' }
& py @arguments
if ($LASTEXITCODE -ne 0) { throw 'Git preservation failed. Read the preceding error; no force push was attempted.' }
