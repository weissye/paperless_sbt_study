[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Username,
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$BaseUrl = 'http://127.0.0.1:9925',
    [ValidateRange(1, 5)][int]$SampleCount = 3
)
$ErrorActionPreference = 'Stop'
$studyRoot = [IO.Path]::GetFullPath($Root)
Set-Location $studyRoot
$drive = [IO.Path]::GetPathRoot($studyRoot).Substring(0,1)
if ((Get-PSDrive -Name $drive).Free -lt 1GB) { throw 'At least 1 GiB free disk space is required.' }
$freeRAM = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB
Write-Host ('Free RAM: {0:N2} GiB' -f $freeRAM)
if ($freeRAM -lt 2) { throw 'At least 2 GiB free RAM is required.' }
$serverContract = Invoke-WebRequest -Uri ($BaseUrl.TrimEnd('/') + '/openapi.json') -UseBasicParsing -TimeoutSec 15
$expectedContract = Get-Content -LiteralPath (Join-Path $studyRoot 'generic-generator\compatibility\contracts\mealie.json') -Raw | ConvertFrom-Json
$liveContract = $serverContract.Content | ConvertFrom-Json
if ($liveContract.info.version -ne $expectedContract.info.version) {
    throw 'Local server version differs from the pinned semantic campaign contract. Replay was not started.'
}
& (Join-Path $PSScriptRoot 'Test-Generic-Generator-Compatibility.ps1') -Root $studyRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Get-StudyPython
$generator = Join-Path $studyRoot 'generic-generator'
$projects = Join-Path $studyRoot 'provengo'
$review = Join-Path $env:USERPROFILE ('Downloads\mealie-semantic-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $review | Out-Null
$savedOptions = $env:JAVA_TOOL_OPTIONS
$previousUsername = $env:SBT_REL_USERNAME
$previousPassword = $env:SBT_REL_PASSWORD
$password = $null
$pointer = [IntPtr]::Zero
$accepted = $false
try {
    $env:JAVA_TOOL_OPTIONS = ("$savedOptions -Xmx1g").Trim()
    $password = Read-Host 'API password (hidden)' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
    $env:SBT_REL_USERNAME = $Username
    $env:SBT_REL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $seed = 208
    foreach ($family in @('merge', 'quantity', 'combined')) {
        $seed++
        $folder = Join-Path $review $family
        New-Item -ItemType Directory -Path $folder | Out-Null
        $before = @(Get-ChildItem -LiteralPath $projects -Directory | ForEach-Object { $_.FullName })
        & (Join-Path $PSScriptRoot 'Prepare-Generic-Provengo-Model.ps1') `
            -Root $studyRoot -OpenApi (Join-Path $generator 'compatibility\contracts\mealie.json') `
            -Name 'mealie' -BaseUrl $BaseUrl -Seed $seed -ResourceMaps -CompileRelationships `
            -RelationshipProfile (Join-Path $generator 'profiles\mealie-relational-semantic-scope.json') `
            -RelationshipRuntime (Join-Path $generator ('profiles\mealie-relational-' + $family + '-runtime.json')) `
            -ReviewZip (Join-Path $folder 'generation.zip')
        $created = @(Get-ChildItem -LiteralPath $projects -Directory | Where-Object {
            $_.FullName -notin $before -and (Test-Path -LiteralPath (Join-Path $_.FullName 'relationship_compilation.json'))
        })
        if ($created.Count -ne 1) { throw ('Could not identify the generated project: ' + $family) }
        $project = $created[0].FullName
        Write-Host ('Family: {0}; project: {1}' -f $family, $project)
        & (Join-Path $PSScriptRoot 'Sample-Generic-Relationship-Model.ps1') `
            -Root $studyRoot -Project $project -Size $SampleCount -ReviewZip (Join-Path $folder 'sampling.zip')
        $samples = Get-Item -LiteralPath (Join-Path $project 'relationship-samples.json')
        Write-Host ('Native sample size: {0:N2} MiB' -f ($samples.Length / 1MB))
        if ($samples.Length -gt 128MB) { throw 'Sample size exceeds the compact replay limit.' }
        for ($sampleId = 1; $sampleId -le $SampleCount; $sampleId++) {
            if ((Get-PSDrive -Name $drive).Free -lt 512MB) { throw 'Replay stopped because disk space is below 512 MiB.' }
            Write-Host ('Replaying {0}, sample {1}/{2}. Only newly owned resources are modified or merged.' -f $family, $sampleId, $SampleCount)
            & $python.Exe @($python.Prefix) (Join-Path $generator 'tools\relationship_execution.py') `
                run --project $project --sample-id $sampleId --review-zip (Join-Path $folder ('live-' + $sampleId + '.zip'))
            if ($LASTEXITCODE -ne 0) { throw 'Semantic replay was not accepted. Campaign stopped at its first failure.' }
        }
    }
    $accepted = $true
} finally {
    $env:JAVA_TOOL_OPTIONS = $savedOptions
    $env:SBT_REL_USERNAME = $previousUsername
    $env:SBT_REL_PASSWORD = $previousPassword
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($null -ne $password) { $password.Dispose() }
    & $python.Exe @($python.Prefix) (Join-Path $generator 'tools\semantic_campaign_review.py') `
        --root $review --expected-runs $SampleCount
    if ($LASTEXITCODE -ne 0) { $accepted = $false; Write-Host 'Campaign evidence is incomplete or rejected. Upload campaign.zip for diagnosis.' }
    Write-Host ('Review ZIP: ' + (Join-Path $review 'campaign.zip'))
}
if (-not $accepted) { throw 'Semantic campaign was not accepted. Evidence was preserved.' }
Write-Host 'SEMANTIC_CAMPAIGN_PASS'
Write-Host 'Upload campaign.zip. No automatic retry or full server reset/replay was performed.'
