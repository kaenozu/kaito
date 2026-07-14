[CmdletBinding()]
param(
    [string]$ArtifactsDir = 'artifacts/release-verifier-tests'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ArtifactsDir = [System.IO.Path]::GetFullPath($ArtifactsDir)
New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null
$WorkDir = Join-Path ([System.IO.Path]::GetTempPath()) ('kaito-release-verifier-test-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null

$Version = '9.9.9'
$Tag = "v$Version"
$Commit = '1111111111111111111111111111111111111111'
$InstallerName = "kaito-installer-$Version.exe"
$createdThumbprint = $null
$previousSigningTestFlag = $env:KAITO_SIGNING_TEST

function Write-Phase {
    param([Parameter(Mandatory = $true)][string]$Name)
    Write-Host "[release-verifier-test] $Name"
}

function Invoke-ExpectedFailure {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action,
        [Parameter(Mandatory = $true)]
        [string]$MessagePattern
    )

    $failed = $false
    try {
        & $Action
    }
    catch {
        $failed = $true
        if ($_.Exception.Message -notmatch $MessagePattern) {
            throw "Expected failure matching '$MessagePattern', but received: $($_.Exception.Message)"
        }
    }
    if (-not $failed) {
        throw "Expected failure matching '$MessagePattern', but the verifier succeeded."
    }
}

function Copy-Package {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $target = Join-Path $WorkDir $Name
    Copy-Item $Source $target -Recurse
    return $target
}

function Write-PackageChecksums {
    param([Parameter(Mandatory = $true)][string]$PackageDir)

    $files = @(
        'kaito.exe',
        $InstallerName,
        'kaito-sbom.cdx.json',
        'RELEASE-METADATA.json'
    )
    $lines = foreach ($name in $files) {
        $path = Join-Path $PackageDir $name
        $hash = (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $name"
    }
    $lines | Set-Content (Join-Path $PackageDir 'SHA256SUMS') -Encoding ascii
}

function Write-PackageMetadata {
    param(
        [Parameter(Mandatory = $true)][string]$PackageDir,
        [Parameter(Mandatory = $true)][ValidateSet('signed', 'unsigned')][string]$SigningResult,
        [AllowNull()][object]$Certificate,
        [switch]$Rehearsal
    )

    $assetNames = @('kaito.exe', $InstallerName, 'kaito-sbom.cdx.json')
    $assets = foreach ($name in $assetNames) {
        $path = Join-Path $PackageDir $name
        $item = Get-Item $path
        [ordered]@{
            name = $name
            sha256 = (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
            size = $item.Length
        }
    }
    $signing = [ordered]@{
        mode = if ($SigningResult -eq 'signed') { 'required' } else { 'disabled' }
        result = $SigningResult
        certificate = $Certificate
    }
    $metadata = [ordered]@{
        schema_version = 1
        version = $Version
        tag = $Tag
        commit = $Commit
        signing = $signing
        assets = $assets
    }
    if ($Rehearsal) {
        $metadata.rehearsal = $true
    }
    $metadata | ConvertTo-Json -Depth 10 |
        Set-Content (Join-Path $PackageDir 'RELEASE-METADATA.json') -Encoding utf8
}

function Invoke-ProductionVerifier {
    param(
        [Parameter(Mandatory = $true)][string]$PackageDir,
        [Parameter(Mandatory = $true)][string]$EvidenceName
    )

    $evidence = Join-Path $ArtifactsDir $EvidenceName
    New-Item -ItemType Directory -Path $evidence -Force | Out-Null
    $parameters = @{
        Profile = 'production'
        PackageDir = $PackageDir
        Version = $Version
        Tag = $Tag
        Commit = $Commit
        ReferenceChecksumsPath = Join-Path $PackageDir 'SHA256SUMS'
        ArtifactsDir = $evidence
    }
    & (Join-Path $PSScriptRoot 'verify_release_package.ps1') @parameters
}

try {
    Write-Phase 'compile two unsigned PE files'
    $compilerCandidates = @(
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
    )
    $compiler = $compilerCandidates |
        Where-Object { Test-Path $_ -PathType Leaf } |
        Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($compiler)) {
        throw 'The .NET Framework C# compiler was not available for the verifier integration test.'
    }

    $sourcePath = Join-Path $WorkDir 'VerifierTestProgram.cs'
    @'
internal static class VerifierTestProgram
{
    private static int Main()
    {
        return 0;
    }
}
'@ | Set-Content $sourcePath -Encoding utf8

    $baseline = Join-Path $WorkDir 'baseline'
    New-Item -ItemType Directory -Path $baseline -Force | Out-Null
    & $compiler '/nologo' '/target:exe' "/out:$(Join-Path $baseline 'kaito.exe')" $sourcePath
    if ($LASTEXITCODE -ne 0) { throw "Unable to compile kaito.exe: $LASTEXITCODE" }
    Copy-Item (Join-Path $baseline 'kaito.exe') (Join-Path $baseline $InstallerName)

    Write-Phase 'create synthetic CycloneDX package identity'
    $bundledProperties = @()
    Get-Content bundled/SHA256SUMS | ForEach-Object {
        if ($_ -notmatch '^(?i)([0-9a-f]{64})\s+(.+)$') {
            throw "Invalid bundled checksum fixture line: $_"
        }
        $bundledProperties += [ordered]@{
            name = "kaito:bundled-file:$($Matches[2].Trim()):sha256"
            value = $Matches[1].ToLowerInvariant()
        }
    }
    $sbom = [ordered]@{
        bomFormat = 'CycloneDX'
        specVersion = '1.6'
        metadata = [ordered]@{
            component = [ordered]@{
                type = 'application'
                name = 'kaito'
                version = $Version
                properties = @(
                    [ordered]@{ name = 'kaito:source-commit'; value = $Commit }
                )
            }
        }
        components = @(
            [ordered]@{
                type = 'application'
                name = '7-Zip'
                version = '26.02'
                properties = $bundledProperties
            }
        )
    }
    $sbom | ConvertTo-Json -Depth 10 |
        Set-Content (Join-Path $baseline 'kaito-sbom.cdx.json') -Encoding utf8
    Write-PackageMetadata -PackageDir $baseline -SigningResult unsigned -Certificate $null
    Write-PackageChecksums -PackageDir $baseline

    Write-Phase 'accept valid unsigned production package'
    Invoke-ProductionVerifier -PackageDir $baseline -EvidenceName 'baseline-unsigned'

    Write-Phase 'reject tampered asset'
    $tampered = Copy-Package -Source $baseline -Name 'tampered'
    Add-Content (Join-Path $tampered 'kaito.exe') 'tampered'
    Invoke-ExpectedFailure -MessagePattern 'Checksum verification failed' -Action {
        Invoke-ProductionVerifier -PackageDir $tampered -EvidenceName 'tampered'
    }

    Write-Phase 'reject unexpected package file'
    $unexpected = Copy-Package -Source $baseline -Name 'unexpected-file'
    Set-Content (Join-Path $unexpected 'unexpected.txt') 'unexpected'
    Invoke-ExpectedFailure -MessagePattern 'exactly five files' -Action {
        Invoke-ProductionVerifier -PackageDir $unexpected -EvidenceName 'unexpected-file'
    }

    Write-Phase 'reject path-like checksum entry'
    $pathLike = Copy-Package -Source $baseline -Name 'path-like-checksum'
    $lines = @(Get-Content (Join-Path $pathLike 'SHA256SUMS'))
    $lines[0] = $lines[0] -replace 'kaito\.exe$', '../outside.exe'
    $lines | Set-Content (Join-Path $pathLike 'SHA256SUMS') -Encoding ascii
    Invoke-ExpectedFailure -MessagePattern 'simple file name without a path' -Action {
        Invoke-ProductionVerifier -PackageDir $pathLike -EvidenceName 'path-like-checksum'
    }

    Write-Phase 'reject rehearsal metadata in production profile'
    $rehearsalMetadata = Copy-Package -Source $baseline -Name 'rehearsal-metadata'
    Write-PackageMetadata -PackageDir $rehearsalMetadata -SigningResult unsigned -Certificate $null -Rehearsal
    Write-PackageChecksums -PackageDir $rehearsalMetadata
    Invoke-ExpectedFailure -MessagePattern 'refuses rehearsal metadata' -Action {
        Invoke-ProductionVerifier -PackageDir $rehearsalMetadata -EvidenceName 'rehearsal-metadata'
    }

    Write-Phase 'reject self-signed binaries in production profile'
    $signedPackage = Copy-Package -Source $baseline -Name 'self-signed'
    $passwordText = [Convert]::ToBase64String(
        [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(24)
    )
    $securePassword = ConvertTo-SecureString $passwordText -AsPlainText -Force
    $certificate = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject 'CN=kaito CI signing test' `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -HashAlgorithm SHA256 `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -KeyExportPolicy Exportable `
        -NotAfter (Get-Date).AddDays(2)
    $createdThumbprint = $certificate.Thumbprint
    $pfxPath = Join-Path $WorkDir 'verifier-test.pfx'
    Export-PfxCertificate -Cert $certificate -FilePath $pfxPath -Password $securePassword | Out-Null
    $certificateBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($pfxPath))
    $signingStatusPath = Join-Path $ArtifactsDir 'self-signed-signing.json'
    $env:KAITO_SIGNING_TEST = '1'
    $signingParameters = @{
        Mode = 'required'
        FilePath = @(
            (Join-Path $signedPackage 'kaito.exe'),
            (Join-Path $signedPackage $InstallerName)
        )
        CertificateBase64 = $certificateBase64
        CertificatePassword = $passwordText
        TimestampUrl = ''
        StatusPath = $signingStatusPath
        VerificationMode = 'test-untrusted'
    }
    & (Join-Path $PSScriptRoot 'sign_windows.ps1') @signingParameters
    $signingStatus = Get-Content $signingStatusPath -Raw | ConvertFrom-Json
    Write-PackageMetadata `
        -PackageDir $signedPackage `
        -SigningResult signed `
        -Certificate $signingStatus.certificate
    Write-PackageChecksums -PackageDir $signedPackage
    Invoke-ExpectedFailure -MessagePattern 'Production SignTool verification failed' -Action {
        Invoke-ProductionVerifier -PackageDir $signedPackage -EvidenceName 'self-signed-production'
    }

    Write-Phase 'all shared production verifier checks passed'
    @(
        'unsigned-production-package: passed'
        'tampered-asset: rejected'
        'unexpected-file: rejected'
        'path-like-checksum: rejected'
        'rehearsal-metadata-in-production: rejected'
        'self-signed-production-signature: rejected'
    ) | Set-Content (Join-Path $ArtifactsDir 'summary.txt') -Encoding utf8
}
finally {
    $env:KAITO_SIGNING_TEST = $previousSigningTestFlag
    if (-not [string]::IsNullOrWhiteSpace($createdThumbprint)) {
        Get-ChildItem "Cert:\CurrentUser\My\$createdThumbprint" -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
}
