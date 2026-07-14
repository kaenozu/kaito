[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('production', 'rehearsal')]
    [string]$Profile,
    [Parameter(Mandatory = $true)]
    [string]$PackageDir,
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [Parameter(Mandatory = $true)]
    [string]$Tag,
    [Parameter(Mandatory = $true)]
    [string]$Commit,
    [string]$ExpectedManifestBase64,
    [string]$ReferenceChecksumsPath,
    [string]$ArtifactsDir = 'artifacts'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$PackageDir = (Resolve-Path $PackageDir).Path
$ArtifactsDir = [System.IO.Path]::GetFullPath($ArtifactsDir)
New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null

function Assert-SimpleFileName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    if (
        [string]::IsNullOrWhiteSpace($Name) -or
        [System.IO.Path]::IsPathRooted($Name) -or
        $Name -in @('.', '..') -or
        $Name.Contains('/') -or
        $Name.Contains('\') -or
        [System.IO.Path]::GetFileName($Name) -ne $Name
    ) {
        throw "$Context must use a simple file name without a path: $Name"
    }
}

function Compare-ExactNames {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Expected,
        [Parameter(Mandatory = $true)]
        [string[]]$Actual,
        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    $expectedSorted = @($Expected | Sort-Object)
    $actualSorted = @($Actual | Sort-Object)
    $difference = @(Compare-Object -ReferenceObject $expectedSorted -DifferenceObject $actualSorted)
    if ($difference.Count -gt 0) {
        throw "$Context is incorrect: $($difference | Out-String)"
    }
}

function Read-ChecksumFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Context
    )

    if (-not (Test-Path $Path -PathType Leaf)) {
        throw "$Context is missing: $Path"
    }

    $entries = [System.Collections.Generic.Dictionary[string, string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $lineCount = 0
    Get-Content $Path | ForEach-Object {
        $lineCount += 1
        if ($_ -notmatch '^(?i)([0-9a-f]{64})\s+(.+)$') {
            throw "$Context contains an invalid line at ${lineCount}: $_"
        }
        $name = $Matches[2].Trim()
        Assert-SimpleFileName -Name $name -Context "$Context filename"
        if ($entries.ContainsKey($name)) {
            throw "$Context contains a duplicate or case-colliding entry: $name"
        }
        $entries.Add($name, $Matches[1].ToLowerInvariant())
    }
    if ($entries.Count -eq 0) {
        throw "$Context contains no checksum entries."
    }
    return ,$entries
}

function Get-SignTool {
    $sdkRoot = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    $candidates = @()
    $direct = Join-Path $sdkRoot 'x64\signtool.exe'
    if (Test-Path $direct -PathType Leaf) { $candidates += $direct }
    $candidates += @(
        Get-ChildItem $sdkRoot -Directory -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName 'x64\signtool.exe' } |
            Where-Object { Test-Path $_ -PathType Leaf }
    )
    $signTool = $candidates | Sort-Object -Descending | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($signTool)) { throw 'signtool.exe was not found.' }
    return $signTool
}

$expectedPackageNames = @(
    'kaito.exe',
    "kaito-installer-$Version.exe",
    'kaito-sbom.cdx.json',
    'RELEASE-METADATA.json',
    'SHA256SUMS'
)
$actualFiles = @(Get-ChildItem $PackageDir -File)
if ($actualFiles.Count -ne 5) {
    throw "Release package must contain exactly five files, found $($actualFiles.Count)."
}
$actualNames = @($actualFiles | ForEach-Object { $_.Name })
$actualNames | ForEach-Object { Assert-SimpleFileName -Name $_ -Context 'Release package file' }
Compare-ExactNames -Expected $expectedPackageNames -Actual $actualNames -Context 'Release package file set'

if ($Profile -eq 'rehearsal' -and [string]::IsNullOrWhiteSpace($ExpectedManifestBase64)) {
    throw 'Rehearsal verification requires ExpectedManifestBase64.'
}
if ($Profile -eq 'production' -and [string]::IsNullOrWhiteSpace($ReferenceChecksumsPath)) {
    throw 'Production verification requires ReferenceChecksumsPath.'
}

if (-not [string]::IsNullOrWhiteSpace($ExpectedManifestBase64)) {
    try {
        $expectedJson = [Text.Encoding]::UTF8.GetString(
            [Convert]::FromBase64String($ExpectedManifestBase64)
        )
    }
    catch {
        throw 'ExpectedManifestBase64 is not valid Base64-encoded UTF-8 JSON.'
    }
    $expectedJson | Set-Content (Join-Path $ArtifactsDir 'expected-package-manifest.json') -Encoding utf8
    $expectedManifest = $expectedJson | ConvertFrom-Json
    if (
        $expectedManifest.schema_version -ne 1 -or
        $expectedManifest.version -ne $Version -or
        $expectedManifest.tag -ne $Tag -or
        $expectedManifest.commit -ne $Commit
    ) {
        throw 'Expected package manifest context is inconsistent.'
    }

    $manifestFiles = @($expectedManifest.files)
    if ($manifestFiles.Count -ne 5) {
        throw "Expected manifest must contain exactly five files, found $($manifestFiles.Count)."
    }
    $manifestNames = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($entry in $manifestFiles) {
        $name = [string]$entry.name
        Assert-SimpleFileName -Name $name -Context 'Expected manifest filename'
        if (-not $manifestNames.Add($name)) {
            throw "Expected manifest contains a duplicate or case-colliding file: $name"
        }
        $path = Join-Path $PackageDir $name
        if (-not (Test-Path $path -PathType Leaf)) { throw "Expected manifest file is missing: $name" }
        $item = Get-Item $path
        $actualHash = (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne [string]$entry.sha256 -or $item.Length -ne [long]$entry.size) {
            throw "Downloaded artifact differs from the build output: $name"
        }
    }
    Compare-ExactNames -Expected $expectedPackageNames -Actual @($manifestNames | ForEach-Object { $_ }) -Context 'Expected manifest file set'
}

$packageChecksumsPath = Join-Path $PackageDir 'SHA256SUMS'
if (-not [string]::IsNullOrWhiteSpace($ReferenceChecksumsPath)) {
    $resolvedReference = (Resolve-Path $ReferenceChecksumsPath).Path
    $referenceHash = (Get-FileHash $resolvedReference -Algorithm SHA256).Hash.ToLowerInvariant()
    $packageHash = (Get-FileHash $packageChecksumsPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($referenceHash -ne $packageHash) {
        throw 'Downloaded SHA256SUMS differs from the locally verified reference file.'
    }
}

$checksums = Read-ChecksumFile -Path $packageChecksumsPath -Context 'SHA256SUMS'
$expectedChecksumNames = @(
    'kaito.exe',
    "kaito-installer-$Version.exe",
    'kaito-sbom.cdx.json',
    'RELEASE-METADATA.json'
)
if ($checksums.Count -ne 4) {
    throw "SHA256SUMS must contain exactly four entries, found $($checksums.Count)."
}
Compare-ExactNames -Expected $expectedChecksumNames -Actual @($checksums.Keys | ForEach-Object { $_ }) -Context 'SHA256SUMS file set'
foreach ($entry in $checksums.GetEnumerator()) {
    $path = Join-Path $PackageDir $entry.Key
    if (-not (Test-Path $path -PathType Leaf)) { throw "Checksummed file is missing: $($entry.Key)" }
    $item = Get-Item $path
    $actualHash = (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $entry.Value) { throw "Checksum verification failed: $($entry.Key)" }
    "$actualHash  $($entry.Key)  $($item.Length) bytes" |
        Add-Content (Join-Path $ArtifactsDir 'verified-sha256.txt') -Encoding ascii
}

$metadataPath = Join-Path $PackageDir 'RELEASE-METADATA.json'
$metadata = Get-Content $metadataPath -Raw | ConvertFrom-Json
if (
    $metadata.schema_version -ne 1 -or
    $metadata.version -ne $Version -or
    $metadata.tag -ne $Tag -or
    $metadata.commit -ne $Commit
) {
    throw 'Release metadata does not match the verification context.'
}
$hasRehearsalFlag = $metadata.PSObject.Properties.Name -contains 'rehearsal'
if ($Profile -eq 'rehearsal') {
    if (-not $hasRehearsalFlag -or $metadata.rehearsal -ne $true) {
        throw 'Rehearsal metadata must explicitly set rehearsal=true.'
    }
}
elseif ($hasRehearsalFlag -and [bool]$metadata.rehearsal) {
    throw 'Production verification refuses rehearsal metadata.'
}

$metadataAssets = @($metadata.assets)
if ($metadataAssets.Count -ne 3) {
    throw "Release metadata must describe exactly three assets, found $($metadataAssets.Count)."
}
$expectedMetadataAssetNames = @(
    'kaito.exe',
    "kaito-installer-$Version.exe",
    'kaito-sbom.cdx.json'
)
$metadataNames = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
foreach ($asset in $metadataAssets) {
    $name = [string]$asset.name
    Assert-SimpleFileName -Name $name -Context 'Release metadata asset name'
    if (-not $metadataNames.Add($name)) {
        throw "Release metadata contains a duplicate or case-colliding asset: $name"
    }
    $path = Join-Path $PackageDir $name
    if (-not (Test-Path $path -PathType Leaf)) { throw "Metadata asset is missing: $name" }
    $item = Get-Item $path
    $actualHash = (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne [string]$asset.sha256 -or $item.Length -ne [long]$asset.size) {
        throw "Release metadata asset identity mismatch: $name"
    }
}
Compare-ExactNames -Expected $expectedMetadataAssetNames -Actual @($metadataNames | ForEach-Object { $_ }) -Context 'Release metadata asset set'

$sbom = Get-Content (Join-Path $PackageDir 'kaito-sbom.cdx.json') -Raw | ConvertFrom-Json
if ($sbom.bomFormat -ne 'CycloneDX' -or $sbom.specVersion -ne '1.6') {
    throw 'Release SBOM is not CycloneDX 1.6.'
}
$sbomRoot = $sbom.metadata.component
if ($sbomRoot.name -ne 'kaito' -or $sbomRoot.version -ne $Version) {
    throw 'Release SBOM root component does not match the release version.'
}
$sourceCommit = @($sbomRoot.properties | Where-Object { $_.name -eq 'kaito:source-commit' })
if ($sourceCommit.Count -ne 1 -or $sourceCommit[0].value -ne $Commit) {
    throw 'Release SBOM source commit does not match the verification context.'
}
$sevenZip = @($sbom.components | Where-Object { $_.name -eq '7-Zip' -and $_.version -eq '26.02' })
if ($sevenZip.Count -ne 1) {
    throw 'Release SBOM does not contain exactly one bundled 7-Zip 26.02 component.'
}
$bundledChecksums = Read-ChecksumFile -Path 'bundled/SHA256SUMS' -Context 'bundled/SHA256SUMS'
foreach ($entry in $bundledChecksums.GetEnumerator()) {
    $propertyName = "kaito:bundled-file:$($entry.Key):sha256"
    $property = @($sevenZip[0].properties | Where-Object { $_.name -eq $propertyName })
    if ($property.Count -ne 1 -or $property[0].value -ne $entry.Value) {
        throw "Release SBOM checksum mismatch for bundled file: $($entry.Key)"
    }
}

$signingResult = [string]$metadata.signing.result
$expectedThumbprint = $null
if ($signingResult -eq 'signed') {
    $expectedThumbprint = [string]$metadata.signing.certificate.thumbprint
}
$signatureEvidence = @()
$signTool = $null
if ($signingResult -eq 'signed') { $signTool = Get-SignTool }

if ($Profile -eq 'rehearsal') {
    if (
        $metadata.signing.mode -ne 'required' -or
        $signingResult -ne 'signed' -or
        $metadata.signing.verification_mode -ne 'test-untrusted'
    ) {
        throw 'Rehearsal metadata does not record the required test-only signing state.'
    }
    if ([string]::IsNullOrWhiteSpace($expectedThumbprint)) {
        throw 'Rehearsal certificate thumbprint is missing.'
    }
    if ($metadata.signing.certificate.subject -ne 'CN=kaito CI signing test') {
        throw 'Rehearsal certificate identity is invalid.'
    }
    $notBefore = [DateTimeOffset]::Parse([string]$metadata.signing.certificate.not_before)
    $notAfter = [DateTimeOffset]::Parse([string]$metadata.signing.certificate.not_after)
    $now = [DateTimeOffset]::UtcNow
    if (($notAfter - $notBefore).TotalDays -gt 3) { throw 'Rehearsal certificate lifetime exceeds three days.' }
    if ($notBefore -gt $now.AddMinutes(5) -or $notAfter -le $now) {
        throw 'Rehearsal certificate is not currently valid.'
    }
}
elseif ($signingResult -notin @('signed', 'unsigned')) {
    throw "Production metadata has an unsupported signing result: $signingResult"
}

foreach ($binaryName in @('kaito.exe', "kaito-installer-$Version.exe")) {
    $binaryPath = Join-Path $PackageDir $binaryName
    $verifyExitCode = $null
    $untrustedRootConfirmed = $false
    $verifyText = $null
    $phase = 'start'

    try {
        if ($signingResult -eq 'signed') {
            $phase = 'signtool-verify'
            $verifyLines = @(& $signTool 'verify' '/pa' '/all' '/v' $binaryPath 2>&1)
            $verifyExitCode = $LASTEXITCODE
            $verifyText = ($verifyLines | ForEach-Object { $_.ToString() }) -join "`n"
            $verifyText | Set-Content (Join-Path $ArtifactsDir "signtool-$binaryName.txt") -Encoding utf8

            if ($Profile -eq 'production') {
                if ($verifyExitCode -ne 0) {
                    throw "Production SignTool verification failed for ${binaryName}: $verifyText"
                }
            }
            elseif ($verifyExitCode -ne 0) {
                $normalized = $verifyText -replace '\s+', ' '
                $untrustedRootPattern = '(?is)(0x800B0109|CERT_E_UNTRUSTEDROOT|terminated in a root.*certificate which is not trusted by the trust provider|root certificate.*not trusted)'
                if ($normalized -notmatch $untrustedRootPattern) {
                    throw "Rehearsal SignTool verification failed with an unexpected error for ${binaryName}: $verifyText"
                }
                $untrustedRootConfirmed = $true
            }
        }

        $phase = 'authenticode-read'
        $signatureResults = @(Get-AuthenticodeSignature -FilePath $binaryPath)
        if ($signatureResults.Count -ne 1) {
            throw "Authenticode returned $($signatureResults.Count) results for $binaryName; exactly one is required."
        }
        $signature = $signatureResults[0]
        $status = $signature.Status.ToString()
        $statusMessage = [string]$signature.StatusMessage
        $signer = $signature.SignerCertificate
        $details = [ordered]@{
            profile = $Profile
            name = $binaryName
            signing_result = $signingResult
            signtool_exit_code = $verifyExitCode
            signtool_untrusted_root_only = $untrustedRootConfirmed
            authenticode_status = $status
            authenticode_status_message = $statusMessage
            signer_present = $null -ne $signer
            signer_subject = if ($null -eq $signer) { $null } else { $signer.Subject }
            signer_issuer = if ($null -eq $signer) { $null } else { $signer.Issuer }
            signer_thumbprint = if ($null -eq $signer) { $null } else { $signer.Thumbprint }
            signer_not_before = if ($null -eq $signer) { $null } else { $signer.NotBefore.ToUniversalTime().ToString('o') }
            signer_not_after = if ($null -eq $signer) { $null } else { $signer.NotAfter.ToUniversalTime().ToString('o') }
        }
        $signatureEvidence += $details
        $details | ConvertTo-Json -Depth 6 |
            Set-Content (Join-Path $ArtifactsDir "authenticode-$binaryName.json") -Encoding utf8

        $phase = 'policy-enforcement'
        if ($signingResult -eq 'unsigned') {
            if ($Profile -ne 'production' -or $status -ne 'NotSigned') {
                throw "Unsigned production asset has an unexpected signature state: $binaryName $status"
            }
            continue
        }

        if ($null -eq $signer) { throw "Embedded signer certificate is missing: $binaryName" }
        if (-not [string]::Equals(
            $signer.Thumbprint,
            $expectedThumbprint,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Embedded signer certificate does not match release metadata: $binaryName"
        }

        if ($Profile -eq 'production') {
            if ($status -ne 'Valid') {
                throw "Production Authenticode verification failed: $binaryName $status"
            }
        }
        else {
            if (
                $signer.Subject -ne 'CN=kaito CI signing test' -or
                $signer.Issuer -ne $signer.Subject -or
                ($signer.NotAfter - $signer.NotBefore).TotalDays -gt 3
            ) {
                throw "Embedded rehearsal certificate identity is invalid: $binaryName"
            }
            if ($untrustedRootConfirmed) {
                if ($status -notin @('Valid', 'NotTrusted', 'UnknownError')) {
                    throw "Unexpected Authenticode status after explicit untrusted-root confirmation: $binaryName $status"
                }
            }
            elseif ($status -ne 'Valid') {
                throw "Rehearsal Authenticode verification failed: $binaryName $status"
            }
        }
    }
    catch {
        [ordered]@{
            schema_version = 1
            profile = $Profile
            name = $binaryName
            phase = $phase
            message = $_.Exception.Message
            fully_qualified_error_id = $_.FullyQualifiedErrorId
            category = [string]$_.CategoryInfo
            position = [string]$_.InvocationInfo.PositionMessage
            script_stack_trace = $_.ScriptStackTrace
        } | ConvertTo-Json -Depth 6 |
            Set-Content (Join-Path $ArtifactsDir "verification-error-$binaryName.json") -Encoding utf8
        throw
    }
}

$signatureEvidence | ConvertTo-Json -Depth 7 |
    Set-Content (Join-Path $ArtifactsDir 'authenticode-summary.json') -Encoding utf8

[ordered]@{
    schema_version = 1
    result = 'passed'
    profile = $Profile
    version = $Version
    tag = $Tag
    commit = $Commit
    file_count = $actualFiles.Count
    signing_result = $signingResult
    certificate_thumbprint = if ($signingResult -eq 'signed') { $expectedThumbprint } else { $null }
} | ConvertTo-Json -Depth 5 |
    Set-Content (Join-Path $ArtifactsDir 'release-package-verification-summary.json') -Encoding utf8

# Accepted rehearsal-only SignTool trust failures must not leak as the step exit code.
$global:LASTEXITCODE = 0
