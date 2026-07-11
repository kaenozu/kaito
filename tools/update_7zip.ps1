[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Version = '26.02'
$PackageUrl = 'https://github.com/ip7z/7zip/releases/download/26.02/7z2602-x64.exe'
$LicenseUrl = 'https://raw.githubusercontent.com/ip7z/7zip/26.02/DOC/License.txt'
$ExpectedPackageSha256 = '__SET_BY_VERIFIED_WORKFLOW__'
$ExpectedExeSha256 = '83967f1b02b43c4efeda302795722c809e0e81b8307de73558d10484d5676a7d'
$ExpectedDllSha256 = '69fd4df057985c40e510e2fac182881c7f85e90aa13ec703f763a8fdb2ce61f8'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BundledDir = Join-Path $RepoRoot 'bundled'
$ExistingExtractor = Join-Path $BundledDir '7z.exe'

if (-not (Test-Path $ExistingExtractor)) {
    throw "Existing bundled extractor is required to unpack the official installer: $ExistingExtractor"
}
if ($ExpectedPackageSha256.StartsWith('__SET_')) {
    throw 'The source package SHA-256 has not been fixed yet'
}

$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("kaito-7zip-update-" + [guid]::NewGuid())
$PackagePath = Join-Path $TempRoot '7zip-installer.exe'
$ExtractDir = Join-Path $TempRoot 'extracted'
$PreparedDir = Join-Path $TempRoot 'prepared'

try {
    New-Item -ItemType Directory -Path $ExtractDir -Force | Out-Null
    New-Item -ItemType Directory -Path $PreparedDir -Force | Out-Null

    Write-Host "Downloading 7-Zip $Version from $PackageUrl"
    Invoke-WebRequest -Uri $PackageUrl -OutFile $PackagePath -UseBasicParsing

    $Signature = Get-AuthenticodeSignature $PackagePath
    if ($Signature.Status -ne 'Valid') {
        throw "Official package signature is not valid: $($Signature.Status)"
    }
    Write-Host "Signer: $($Signature.SignerCertificate.Subject)"

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

    # All verification has completed. Replace each destination through a same-directory temp file.
    foreach ($Name in @('7z.exe', '7z.dll', '7-ZIP-LICENSE.txt', 'SHA256SUMS')) {
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
