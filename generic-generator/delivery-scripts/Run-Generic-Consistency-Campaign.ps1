[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Username,
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$BaseUrl = 'http://127.0.0.1:9925',
    [ValidateRange(1, 5)][int]$SampleCount = 3
)
$ErrorActionPreference = 'Stop'
$studyRoot = [IO.Path]::GetFullPath($Root)
if ((Get-PSDrive -Name ([IO.Path]::GetPathRoot($studyRoot).Substring(0,1))).Free -lt 1GB) {
    throw 'At least 1 GiB of free disk space is required.'
}
Invoke-WebRequest -Uri ($BaseUrl.TrimEnd('/') + '/openapi.json') -UseBasicParsing -TimeoutSec 15 | Out-Null
& (Join-Path $PSScriptRoot 'Test-Generic-Generator-Compatibility.ps1') -Root $studyRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Get-StudyPython
$generator = Join-Path $studyRoot 'generic-generator'
$projects = Join-Path $studyRoot 'provengo'
$before = @(Get-ChildItem -LiteralPath $projects -Directory | ForEach-Object { $_.FullName })
$review = Join-Path $env:USERPROFILE ('Downloads\mealie-consistency-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $review | Out-Null
& (Join-Path $PSScriptRoot 'Prepare-Generic-Provengo-Model.ps1') `
    -Root $studyRoot -OpenApi (Join-Path $generator 'compatibility\contracts\mealie.json') `
    -Name 'mealie' -BaseUrl $BaseUrl -Seed 207 -ResourceMaps -CompileRelationships `
    -RelationshipProfile (Join-Path $generator 'profiles\mealie-relational-alternate-paths.json') `
    -RelationshipRuntime (Join-Path $generator 'profiles\mealie-relational-consistency-runtime.json') `
    -ReviewZip (Join-Path $review 'generation.zip')
$created = @(Get-ChildItem -LiteralPath $projects -Directory | Where-Object {
    $_.FullName -notin $before -and (Test-Path -LiteralPath (Join-Path $_.FullName 'relationship_compilation.json'))
})
if ($created.Count -ne 1) { throw 'Could not identify the new consistency project.' }
$project = $created[0].FullName
Write-Host ('Project: ' + $project)
$freeRAM = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB
Write-Host ('Free RAM: {0:N2} GiB' -f $freeRAM)
if ($freeRAM -lt 2) { throw 'At least 2 GiB free RAM is required. The generated project is preserved.' }
$savedOptions = $env:JAVA_TOOL_OPTIONS
$previousUsername = $env:SBT_REL_USERNAME
$previousPassword = $env:SBT_REL_PASSWORD
$password = $null
$pointer = [IntPtr]::Zero
$liveReviews = @()
try {
    $env:JAVA_TOOL_OPTIONS = ("$savedOptions -Xmx1g").Trim()
    & (Join-Path $PSScriptRoot 'Sample-Generic-Relationship-Model.ps1') `
        -Root $studyRoot -Project $project -Size $SampleCount -ReviewZip (Join-Path $review 'sampling.zip')
    $samples = Get-Item -LiteralPath (Join-Path $project 'relationship-samples.json')
    Write-Host ('Native sample size: {0:N2} MiB' -f ($samples.Length / 1MB))
    if ($samples.Length -gt 128MB) { throw 'Compact samples exceeded 128 MiB. Live replay was not started.' }
    $password = Read-Host 'API password (hidden)' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
    $env:SBT_REL_USERNAME = $Username
    $env:SBT_REL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    for ($sampleId = 1; $sampleId -le $SampleCount; $sampleId++) {
        $liveZip = Join-Path $review ('live-' + $sampleId + '.zip')
        $liveReviews += $liveZip
        Write-Host ('Replaying native sample {0}/{1}. New owned tags and categories will be detached and deleted.' -f $sampleId, $SampleCount)
        & $python.Exe @($python.Prefix) (Join-Path $generator 'tools\relationship_execution.py') `
            run --project $project --sample-id $sampleId --review-zip $liveZip
        if ($LASTEXITCODE -ne 0) { throw 'Native consistency replay was not accepted. The campaign stopped at its first failure.' }
    }
} finally {
    $env:JAVA_TOOL_OPTIONS = $savedOptions
    $env:SBT_REL_USERNAME = $previousUsername
    $env:SBT_REL_PASSWORD = $previousPassword
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($null -ne $password) { $password.Dispose() }
    if ($liveReviews.Count -gt 0) {
        & $python.Exe @($python.Prefix) (Join-Path $generator 'tools\relationship_sample_campaign.py') `
            --expected-runs $SampleCount --output (Join-Path $review 'campaign.zip') --reviews @liveReviews
        if ($LASTEXITCODE -ne 0) { Write-Host 'Campaign evidence is incomplete or rejected. Upload campaign.zip for diagnosis.' }
    }
    Write-Host ('Review folder: ' + $review)
}
Write-Host 'Upload campaign.zip. No automatic retry or full server reset/replay was performed.'
