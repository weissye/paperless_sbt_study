[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Username,
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [string]$BaseUrl = 'http://127.0.0.1:9925',
    [int]$Seed = (Get-Random -Minimum 217 -Maximum 1000000)
)
$ErrorActionPreference = 'Stop'
$studyRoot = [IO.Path]::GetFullPath($Root)
$generator = Join-Path $studyRoot 'generic-generator'
$projects = Join-Path $studyRoot 'provengo'
$review = Join-Path $env:USERPROFILE ('Downloads\mealie-route-identity-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $review | Out-Null
$server = Invoke-WebRequest -Uri ($BaseUrl.TrimEnd('/') + '/openapi.json') -UseBasicParsing -TimeoutSec 15
$expected = Get-Content -LiteralPath (Join-Path $generator 'compatibility\contracts\mealie.json') -Raw | ConvertFrom-Json
if (($server.Content | ConvertFrom-Json).info.version -ne $expected.info.version) {
    throw 'Local server differs from the pinned contract version.'
}
$freeRAMMiB = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1KB
Write-Host ('Free RAM: {0:N0} MiB; Java heap limit: 512 MiB.' -f $freeRAMMiB)
if ($freeRAMMiB -lt 1024) {
    throw ('At least 1024 MiB free RAM is required; currently {0:N0} MiB is available. No campaign was started.' -f $freeRAMMiB)
}
if ((Get-PSDrive -Name ([IO.Path]::GetPathRoot($studyRoot).Substring(0,1))).Free -lt 1GB) {
    throw 'At least 1 GiB free disk space is required.'
}
& (Join-Path $PSScriptRoot 'Test-Generic-Generator-Compatibility.ps1') -Root $studyRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Get-StudyPython
[pscustomobject]@{seed=$Seed; scope='name-driven route migration and old-alias reuse with raw write and read evidence'; contract_version=$expected.info.version} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $review 'campaign-config.json') -Encoding UTF8
$savedOptions = $env:JAVA_TOOL_OPTIONS
$savedUsername = $env:SBT_REL_USERNAME
$savedPassword = $env:SBT_REL_PASSWORD
$password = $null
$pointer = [IntPtr]::Zero
$summary = @()
try {
    $env:JAVA_TOOL_OPTIONS = ("$savedOptions -Xmx512m").Trim()
    $password = Read-Host 'API password (hidden)' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
    $env:SBT_REL_USERNAME = $Username
    $env:SBT_REL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $cases = @('control', 'rename', 'reuse')
    foreach ($case in $cases) {
        $caseReview = Join-Path $review $case
        New-Item -ItemType Directory -Path $caseReview | Out-Null
        $before = @(Get-ChildItem -LiteralPath $projects -Directory | ForEach-Object { $_.FullName })
        & (Join-Path $PSScriptRoot 'Prepare-Generic-Provengo-Model.ps1') `
            -Root $studyRoot -OpenApi (Join-Path $generator 'compatibility\contracts\mealie.json') `
            -Name 'mealie' -BaseUrl $BaseUrl -Seed $Seed -ResourceMaps -CompileRelationships `
            -RelationshipProfile (Join-Path $generator ("profiles\mealie-route-$case-scope.json")) `
            -RelationshipRuntime (Join-Path $generator ("profiles\mealie-route-$case-runtime.json")) `
            -ReviewZip (Join-Path $caseReview 'generation.zip')
        $created = @(Get-ChildItem -LiteralPath $projects -Directory | Where-Object {
            $_.FullName -notin $before -and (Test-Path -LiteralPath (Join-Path $_.FullName 'relationship_compilation.json'))
        })
        if ($created.Count -ne 1) { throw 'Could not identify the new control project.' }
        $project = $created[0].FullName
        & (Join-Path $PSScriptRoot 'Sample-Generic-Relationship-Model.ps1') `
            -Root $studyRoot -Project $project -Size 2 -ReviewZip (Join-Path $caseReview 'sampling.zip')
        if ((Get-Item -LiteralPath (Join-Path $project 'relationship-samples.json')).Length -gt 128MB) {
            throw 'Compact samples exceeded 128 MiB.'
        }
        foreach ($sampleId in @(1,2)) {
            $liveZip = Join-Path $caseReview ("live-$sampleId.zip")
            Write-Host "Campaign: $case; sample: $sampleId. New owned resources will be created."
            & $python.Exe @($python.Prefix) (Join-Path $generator 'tools\relationship_execution.py') `
                run --project $project --sample-id $sampleId --review-zip $liveZip
            $nativeCode = $LASTEXITCODE
            if (-not (Test-Path -LiteralPath $liveZip)) { throw 'Native review was not produced.' }
            & $python.Exe @($python.Prefix) -B (Join-Path $generator 'tools\route_raw_evidence.py') `
                --review $liveZip --output (Join-Path $caseReview ("raw-evidence-$sampleId.json"))
            if ($LASTEXITCODE -ne 0) { throw 'Raw route evidence extraction failed. Preserve the native review.' }
            $resultFile = Join-Path $caseReview ("result-$sampleId.json")
            & $python.Exe @($python.Prefix) (Join-Path $generator 'tools\classify_reference_review.py') `
                --review $liveZip --output $resultFile
            $classificationCode = $LASTEXITCODE
            $result = Get-Content -LiteralPath $resultFile -Raw | ConvertFrom-Json
            $summary += [pscustomobject]@{case=$case; sample=$sampleId; project=$project; native_exit=$nativeCode; status=$result.status; seed=$Seed; review=$liveZip; sha256=(Get-FileHash -LiteralPath $liveZip -Algorithm SHA256).Hash}
            if (($case -eq 'control') -and $result.status -ne 'PASS') { throw 'Matched control did not pass. Route probes were not accepted.' }
            if ($classificationCode -ne 0) { throw 'Authentication, infrastructure or unclassified failure. Campaign stopped; inspect preserved evidence.' }
        }
    }
} finally {
    $env:JAVA_TOOL_OPTIONS = $savedOptions
    $env:SBT_REL_USERNAME = $savedUsername
    $env:SBT_REL_PASSWORD = $savedPassword
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($null -ne $password) { $password.Dispose() }
    [pscustomobject]@{runs=$summary; reset_replay_accepted=$false; new_bug_count_confirmed=$false} |
        ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $review 'campaign-summary.json') -Encoding UTF8
    $campaignZip = Join-Path $review 'campaign.zip'
    $contents = @(Get-ChildItem -LiteralPath $review | Where-Object { $_.Name -ne 'campaign.zip' } | ForEach-Object { $_.FullName })
    Compress-Archive -LiteralPath $contents -DestinationPath $campaignZip
    Write-Host "Review ZIP: $campaignZip"
}
Write-Host 'ROUTE_IDENTITY_COMPLETE_FOR_REVIEW. No deletion or merge was requested. Candidates require independent analysis and reproduction.'
