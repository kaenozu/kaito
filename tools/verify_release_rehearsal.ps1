[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackageDir,
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [Parameter(Mandatory = $true)]
    [string]$RehearsalTag,
    [Parameter(Mandatory = $true)]
    [string]$Commit,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedManifestBase64,
    [string]$ArtifactsDir = 'artifacts'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$PackageDir = (Resolve-Path $PackageDir).Path
$ArtifactsDir = [System.IO.Path]::GetFullPath($ArtifactsDir)
New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null

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

$expectedJson = [Text.Encoding]::UTF8.GetString(
    [Convert]::FromBase64String($ExpectedManifestBase64)
)
$expectedJson | Set-Content (Join-Path $ArtifactsDir 'rehearsal-expected-manifest.json') -Encoding utf8
$expectedManifest = $expectedJson | ConvertFrom-Json
if (
    $expectedManifest.schema_version -ne 1 -or
    $expectedManifest.version -ne $Version -or
    $expectedManifest.tag -ne $RehearsalTag -or
    $expectedManifest.commit -ne $Commit
) {
    throw 'Expected package manifest context is inconsistent.'
}

$expectedFiles = @($expectedManifest.files)
if ($expectedFiles.Count -ne 5) {
    throw "Expected manifest must contain exactly five files, found $($expectedFiles.Count)."
}
$actualFiles = @(Get-ChildItem $PackageDir -File)
if ($actualFiles.Count -ne 5) {
    throw "Downloaded package must contain exactly five files, found $($actualFiles.Count)."
}
$expectedNames = @($expectedFiles | ForEach-Object { $_.name } | Sort-Object)
$actualNames = @($actualFiles | ForEach-Object { $_.Name } | Sort-Object)
$nameDifference = @(Compare-Object -ReferenceObject $expectedNames -DifferenceObject $actualNames)
if ($nameDifference.Count -gt 0) {
    throw "Downloaded package file set differs from the build manifest: $($nameDifference | Out-String)"
}

foreach ($entry in $expectedFiles) {
    $path = Join-Path $PackageDir $entry.name
    $item = Get-Item $path
    $actualHash = (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $entry.sha256 -or $item.Length -ne $entry.size) {
        throw "Downloaded artifact differs from the build output: $($entry.name)"
    }
    "$actualHash  $($entry.name)  $($item.Length) bytes" |
        Add-Content (Join-Path $ArtifactsDir 'redownloaded-sha256.txt') -Encoding ascii
}

$checksumPath = Join-Path $PackageDir 'SHA256SUMS'
$checksums = @{}
Get-Content $checksumPath | ForEach-Object {
    if ($_ -notmatch '^([0-9a-f]{64})\s+(.+)$') { throw "Invalid checksum line: $_" }
    $name = $Matches[2].Trim()
    if ($checksums.ContainsKey($name)) { throw "Duplicate checksum entry: $name" }
    $checksums[$name] = $Matches[1]
}
if ($checksums.Count -ne 4) {
    throw "SHA256SUMS must contain exactly four entries, found $($checksums.Count)."
}
$expectedChecksumNames = @(
    'kaito.exe',
    "kaito-installer-$Version.exe",
    'kaito-sbom.cdx.json',
    'RELEASE-METADATA.json'
) | Sort-Object
$actualChecksumNames = @($checksums.Keys | Sort-Object)
$checksumNameDifference = @(Compare-Object -ReferenceObject $expectedChecksumNames -DifferenceObject $actualChecksumNames)
if ($checksumNameDifference.Count -gt 0) {
    throw "SHA256SUMS file set is incorrect: $($checksumNameDifference | Out-String)"
}
foreach ($entry in $checksums.GetEnumerator()) {
    $path = Join-Path $PackageDir $entry.Key
    if (-not (Test-Path $path -PathType Leaf)) { throw "Checksummed file is missing: $($entry.Key)" }
    $actualHash = (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $entry.Value) { throw "Checksum verification failed: $($entry.Key)" }
}

$metadataPath = Join-Path $PackageDir 'RELEASE-METADATA.json'
$metadata = Get-Content $metadataPath -Raw | ConvertFrom-Json
if (
    $metadata.schema_version -ne 1 -or
    $metadata.rehearsal -ne $true -or
    $metadata.version -ne $Version -or
    $metadata.tag -ne $RehearsalTag -or
    $metadata.commit -ne $Commit
) {
    throw 'Release metadata does not match the rehearsal context.'
}
if (
    $metadata.signing.mode -ne 'required' -or
    $metadata.signing.result -ne 'signed' -or
    $metadata.signing.verification_mode -ne 'test-untrusted'
) {
    throw 'Release metadata does not record the required rehearsal signing state.'
}
$expectedThumbprint = [string]$metadata.signing.certificate.thumbprint
if ([string]::IsNullOrWhiteSpace($expectedThumbprint)) {
    throw 'Release metadata certificate thumbprint is missing.'
}
if ($metadata.signing.certificate.subject -ne 'CN=kaito CI signing test') {
    throw 'Release metadata certificate identity is invalid.'
}
$notBefore = [DateTimeOffset]::Parse([string]$metadata.signing.certificate.not_before)
$notAfter = [DateTimeOffset]::Parse([string]$metadata.signing.certificate.not_after)
$now = [DateTimeOffset]::UtcNow
if (($notAfter - $notBefore).TotalDays -gt 3) { throw 'Rehearsal certificate lifetime exceeds three days.' }
if ($notBefore -gt $now.AddMinutes(5) -or $notAfter -le $now) {
    throw 'Rehearsal certificate is not currently valid.'
}

$metadataAssets = @($metadata.assets)
if ($metadataAssets.Count -ne 3) {
    throw "Release metadata must describe exactly three assets, found $($metadataAssets.Count)."
}
$expectedMetadataAssetNames = @(
    'kaito.exe',
    "kaito-installer-$Version.exe",
    'kaito-sbom.cdx.json'
) | Sort-Object
$actualMetadataAssetNames = @($metadataAssets | ForEach-Object { $_.name } | Sort-Object)
$metadataNameDifference = @(Compare-Object -ReferenceObject $expectedMetadataAssetNames -DifferenceObject $actualMetadataAssetNames)
if ($metadataNameDifference.Count -gt 0) {
    throw "Release metadata asset set is incorrect: $($metadataNameDifference | Out-String)"
}
foreach ($asset in $metadataAssets) {
    $path = Join-Path $PackageDir $asset.name
    if (-not (Test-Path $path -PathType Leaf)) { throw "Metadata asset is missing: $($asset.name)" }
    $item = Get-Item $path
    $actualHash = (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $asset.sha256 -or $item.Length -ne $asset.size) {
        throw "Metadata asset identity mismatch: $($asset.name)"
    }
}

$sbom = Get-Content (Join-Path $PackageDir 'kaito-sbom.cdx.json') -Raw | ConvertFrom-Json
if ($sbom.bomFormat -ne 'CycloneDX' -or $sbom.specVersion -ne '1.6') {
    throw 'Rehearsal SBOM is not CycloneDX 1.6.'
}
$sbomRoot = $sbom.metadata.component
if ($sbomRoot.name -ne 'kaito' -or $sbomRoot.version -ne $Version) {
    throw 'Rehearsal SBOM root component does not match the project version.'
}
$sourceCommit = @($sbomRoot.properties | Where-Object { $_.name -eq 'kaito:source-commit' })
if ($sourceCommit.Count -ne 1 -or $sourceCommit[0].value -ne $Commit) {
    throw 'Rehearsal SBOM source commit does not match the build commit.'
}
$sevenZip = @($sbom.components | Where-Object { $_.name -eq '7-Zip' -and $_.version -eq '26.02' })
if ($sevenZip.Count -ne 1) {
    throw 'Rehearsal SBOM does not contain exactly one bundled 7-Zip 26.02 component.'
}
Get-Content bundled/SHA256SUMS | ForEach-Object {
    if ($_ -notmatch '^([0-9a-f]{64})\s+(.+)$') { throw "Invalid bundled checksum line: $_" }
    $expectedHash = $Matches[1]
    $bundledName = $Matches[2].Trim()
    $propertyName = "kaito:bundled-file:${bundledName}:sha256"
    $property = @($sevenZip[0].properties | Where-Object { $_.name -eq $propertyName })
    if ($property.Count -ne 1 -or $property[0].value -ne $expectedHash) {
        throw "Rehearsal SBOM checksum mismatch for bundled file: $bundledName"
    }
}

$signTool = Get-SignTool
$signatureEvidence = @()
foreach ($binaryName in @('kaito.exe', "kaito-installer-$Version.exe")) {
    $binaryPath = Join-Path $PackageDir $binaryName
    $verifyLines = @(& $signTool 'verify' '/pa' '/all' '/v' $binaryPath 2>&1)
    $verifyExitCode = $LASTEXITCODE
    $verifyText = ($verifyLines | ForEach-Object { $_.ToString() }) -join "`n"
    $verifyText | Set-Content (Join-Path $ArtifactsDir "signtool-$binaryName.txt") -Encoding utf8
    $verifyNormalized = $verifyText -replace '\s+', ' '
    $untrustedRootConfirmed = $false
    if ($verifyExitCode -ne 0) {
        $untrustedRootPattern = '(?i)(0x800B0109|CERT_E_UNTRUSTEDROOT|terminated in a root certificate which is not trusted|root certificate.*not trusted)'
        if ($verifyNormalized -notmatch $untrustedRootPattern) {
            throw "SignTool verification failed with an unexpected error for ${binaryName}: $verifyText"
        }
        $untrustedRootConfirmed = $true
    }

    $signature = Get-AuthenticodeSignature $binaryPath
    $signatureStatus = $signature.Status.ToString()
    $signer = $signature.SignerCertificate
    $details = [ordered]@{
        name = $binaryName
        signtool_exit_code = $verifyExitCode
        signtool_untrusted_root_only = $untrustedRootConfirmed
        authenticode_status = $signatureStatus
        authenticode_status_message = $signature.StatusMessage
        signer_present = $null -ne $signer
        signer_subject = if ($null -eq $signer) { $null } else { $signer.Subject }
        signer_issuer = if ($null -eq $signer) { $null } else { $signer.Issuer }
        signer_thumbprint = if ($null -eq $signer) { $null } else { $signer.Thumbprint }
        signer_not_before = if ($null -eq $signer) { $null } else { $signer.NotBefore.ToUniversalTime().ToString('o') }
        signer_not_after = if ($null -eq $signer) { $null } else { $signer.NotAfter.ToUniversalTime().ToString('o') }
    }
    $signatureEvidence += $details
    $details | ConvertTo-Json -Depth 5 |
        Set-Content (Join-Path $ArtifactsDir "authenticode-$binaryName.json") -Encoding utf8

    if ($null -eq $signer) { throw "Embedded signer certificate is missing: $binaryName" }
    if (
        $signer.Subject -ne 'CN=kaito CI signing test' -or
        $signer.Issuer -ne $signer.Subject -or
        ($signer.NotAfter - $signer.NotBefore).TotalDays -gt 3
    ) {
        throw "Embedded rehearsal certificate identity is invalid: $binaryName"
    }
    if (-not [string]::Equals(
        $signer.Thumbprint,
        $expectedThumbprint,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Embedded signer certificate does not match release metadata: $binaryName"
    }
    if ($untrustedRootConfirmed) {
        if ($signatureStatus -notin @('Valid', 'NotTrusted', 'UnknownError')) {
            throw "Unexpected Authenticode status after explicit untrusted-root confirmation: $binaryName $signatureStatus"
        }
    }
    elseif ($signatureStatus -ne 'Valid') {
        throw "Authenticode verification failed: $binaryName $signatureStatus"
    }
}
$signatureEvidence | ConvertTo-Json -Depth 6 |
    Set-Content (Join-Path $ArtifactsDir 'authenticode-summary.json') -Encoding utf8

[ordered]@{
    schema_version = 1
    result = 'passed'
    version = $Version
    tag = $RehearsalTag
    commit = $Commit
    file_count = $actualFiles.Count
    signing_result = $metadata.signing.result
    certificate_thumbprint = $expectedThumbprint
} | ConvertTo-Json -Depth 5 |
    Set-Content (Join-Path $ArtifactsDir 'rehearsal-verification-summary.json') -Encoding utf8

# Expected test-only SignTool trust failures are accepted above and must not leak as the step exit code.
$global:LASTEXITCODE = 0
