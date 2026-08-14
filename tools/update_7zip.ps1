[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BundledDir = Join-Path $RepoRoot 'bundled'

# 7-Zip のピン留め定義（バージョン・URL・SHA-256）は bundled/7zip-pinned.json に一元管理。
# tools/update_7zip.ps1 と ci.yml の両方がこの JSON を参照する。
$PinnedPath = Join-Path $BundledDir '7zip-pinned.json'
if (-not (Test-Path $PinnedPath -PathType Leaf)) {
    throw "Pinned 7-Zip definition not found: $PinnedPath"
}
$Pinned = Get-Content $PinnedPath -Raw | ConvertFrom-Json

$Version = $Pinned.version
$PackageUrl = $Pinned.package_url
$LicenseUrl = $Pinned.license_url
$ExpectedPackageSha256 = $Pinned.package_sha256
$ExpectedExeSha256 = $Pinned.exe_sha256
$ExpectedDllSha256 = $Pinned.dll_sha256
$ExistingExtractor = Join-Path $BundledDir '7z.exe'

if (-not (Test-Path $ExistingExtractor -PathType Leaf)) {
    throw "Existing bundled extractor is required to unpack the official installer: $ExistingExtractor"
}
$ExistingHash = (Get-FileHash $ExistingExtractor -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ExistingHash -ne $ExpectedExeSha256) {
    throw "Existing bundled extractor hash mismatch: $ExistingHash"
}

$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('kaito-7zip-update-' + [guid]::NewGuid())
$PackagePath = Join-Path $TempRoot '7zip-installer.exe'
$ExtractDir = Join-Path $TempRoot 'extracted'
$PreparedDir = Join-Path $TempRoot 'prepared'

try {
    New-Item -ItemType Directory -Path $ExtractDir -Force | Out-Null
    New-Item -ItemType Directory -Path $PreparedDir -Force | Out-Null

    Write-Host "Downloading 7-Zip $Version from $PackageUrl"
    Invoke-WebRequest -Uri $PackageUrl -OutFile $PackagePath -UseBasicParsing

    # The official 26.02 x64 release asset is not Authenticode-signed.
    # Verify the fixed official release URL and pinned package digest before
    # parsing the package with the already-pinned bundled extractor.
    $PackageHash = (Get-FileHash $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($PackageHash -ne $ExpectedPackageSha256) {
        throw "Source package hash mismatch: $PackageHash"
    }
    Write-Host "Source package SHA-256: $PackageHash"

    & $ExistingExtractor x $PackagePath "-o$ExtractDir" -y | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to extract official package: exit $LASTEXITCODE"
    }

    $CandidateExe = Get-ChildItem $ExtractDir -Filter '7z.exe' -Recurse | Select-Object -First 1
    $CandidateDll = Get-ChildItem $ExtractDir -Filter '7z.dll' -Recurse | Select-Object -First 1
    if ($null -eq $CandidateExe -or $null -eq $CandidateDll) {
        throw 'The official package did not contain 7z.exe and 7z.dll'
    }

    $ExeHash = (Get-FileHash $CandidateExe.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $DllHash = (Get-FileHash $CandidateDll.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ExeHash -ne $ExpectedExeSha256) {
        throw "7z.exe hash mismatch: $ExeHash"
    }
    if ($DllHash -ne $ExpectedDllSha256) {
        throw "7z.dll hash mismatch: $DllHash"
    }

    $VersionOutput = (& $CandidateExe.FullName i -sccUTF-8 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0 -or $VersionOutput -notmatch "7-Zip\s+$([regex]::Escape($Version))") {
        throw "Unexpected 7-Zip version output: $VersionOutput"
    }

    $PreparedExe = Join-Path $PreparedDir '7z.exe'
    $PreparedDll = Join-Path $PreparedDir '7z.dll'
    $PreparedLicense = Join-Path $PreparedDir '7-ZIP-LICENSE.txt'
    $PreparedManifest = Join-Path $PreparedDir 'SHA256SUMS'
    $PreparedSourceNotice = Join-Path $PreparedDir 'SOURCE-PACKAGE.txt'
    Copy-Item $CandidateExe.FullName $PreparedExe
    Copy-Item $CandidateDll.FullName $PreparedDll
    Invoke-WebRequest -Uri $LicenseUrl -OutFile $PreparedLicense -UseBasicParsing

    $LicenseText = Get-Content $PreparedLicense -Raw
    if ($LicenseText -notmatch 'GNU LGPL' -or $LicenseText -notmatch 'unRAR license restriction') {
        throw 'Downloaded license text does not contain the expected notices'
    }

    @(
        "$ExpectedExeSha256  7z.exe"
        "$ExpectedDllSha256  7z.dll"
    ) | Set-Content $PreparedManifest -Encoding ascii

    @(
        "Source: $PackageUrl"
        'Authenticode: NotSigned'
        "SHA-256: $PackageHash"
        "Pinned definition: bundled/7zip-pinned.json"
        "Verified on: $([DateTime]::UtcNow.ToString('yyyy-MM-dd'))"
        ''
        'The package is verified before extraction. Extracted binaries are verified against SHA256SUMS before replacement.'
    ) | Set-Content $PreparedSourceNotice -Encoding utf8

    # All checks completed. Replace destinations only after every candidate passed.
    foreach ($Name in @('7z.exe', '7z.dll', '7-ZIP-LICENSE.txt', 'SHA256SUMS', 'SOURCE-PACKAGE.txt')) {
        $Source = Join-Path $PreparedDir $Name
        $Destination = Join-Path $BundledDir $Name
        $TemporaryDestination = "$Destination.new"
        Copy-Item $Source $TemporaryDestination -Force
        Move-Item $TemporaryDestination $Destination -Force
    }

    Write-Host "Updated bundled 7-Zip $Version successfully."
    Write-Host "Source package SHA-256: $PackageHash"
    Write-Host "7z.exe SHA-256: $ExeHash"
    Write-Host "7z.dll SHA-256: $DllHash"
}
finally {
    Remove-Item $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
