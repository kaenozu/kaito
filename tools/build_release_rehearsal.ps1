[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [Parameter(Mandatory = $true)]
    [string]$RehearsalTag,
    [Parameter(Mandatory = $true)]
    [string]$Commit,
    [string]$ArtifactsDir = 'artifacts',
    [string]$DistDir = 'dist'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ArtifactsDir = [System.IO.Path]::GetFullPath($ArtifactsDir)
$DistDir = [System.IO.Path]::GetFullPath($DistDir)
New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null
New-Item -ItemType Directory -Path $DistDir -Force | Out-Null

function Invoke-CheckedNative {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage Exit code: $LASTEXITCODE"
    }
}

function Assert-Unsigned {
    param([Parameter(Mandatory = $true)][string]$Path)

    $signature = Get-AuthenticodeSignature $Path
    if ($signature.Status -ne 'NotSigned') {
        throw "Rehearsal binary was unexpectedly signed before the signing step: $Path $($signature.Status)"
    }
}

function Test-SignedExecutable {
    param([Parameter(Mandatory = $true)][string]$ExecutablePath)

    $versionFile = Join-Path $ArtifactsDir 'rehearsal-version.txt'
    $selfTestFile = Join-Path $ArtifactsDir 'rehearsal-self-test.txt'
    $backendFile = Join-Path $ArtifactsDir 'rehearsal-backend.json'
    $archiveSmokeFile = Join-Path $ArtifactsDir 'rehearsal-archive-smoke.json'
    $diagnosticsFile = Join-Path $ArtifactsDir 'rehearsal-diagnostics.json'

    $process = Start-Process -FilePath $ExecutablePath -ArgumentList @('--version', '--output', $versionFile) -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Version process failed: $($process.ExitCode)" }
    if ((Get-Content $versionFile -Raw).Trim() -ne "kaito $Version") { throw 'Version output mismatch.' }

    $process = Start-Process -FilePath $ExecutablePath -ArgumentList @('--self-test', '--output', $selfTestFile) -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Self-test process failed: $($process.ExitCode)" }
    if ((Get-Content $selfTestFile -Raw) -notmatch 'All checks passed') { throw 'Self-test failed.' }

    $process = Start-Process -FilePath $ExecutablePath -ArgumentList @('--backend-info', '--json', '--output', $backendFile) -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Backend-info process failed: $($process.ExitCode)" }
    $backend = Get-Content $backendFile -Raw | ConvertFrom-Json
    if (
        $backend.source -ne 'bundled' -or
        $backend.version -ne '26.02' -or
        $backend.integrity -ne 'ok' -or
        $backend.sha256 -ne $backend.expected_sha256
    ) {
        throw "Backend verification failed: $($backend | ConvertTo-Json -Compress)"
    }

    $process = Start-Process -FilePath $ExecutablePath -ArgumentList @('--archive-smoke', '--json', '--output', $archiveSmokeFile) -Wait -PassThru
    if ($process.ExitCode -ne 0 -or -not (Test-Path $archiveSmokeFile -PathType Leaf)) {
        throw 'Archive smoke process failed.'
    }
    $archiveSmoke = Get-Content $archiveSmokeFile -Raw | ConvertFrom-Json
    if ($archiveSmoke.failed -ne 0 -or $archiveSmoke.passed -ne 6) {
        throw "Archive smoke verification failed: $($archiveSmoke | ConvertTo-Json -Depth 8 -Compress)"
    }

    $process = Start-Process -FilePath $ExecutablePath -ArgumentList @('--diagnostics', '--output', $diagnosticsFile) -Wait -PassThru
    if ($process.ExitCode -ne 0 -or -not (Test-Path $diagnosticsFile -PathType Leaf)) {
        throw 'Diagnostics command failed.'
    }
    $diagnostics = Get-Content $diagnosticsFile -Raw | ConvertFrom-Json
    if ($diagnostics.application.version -ne $Version -or $diagnostics.backend.integrity -ne 'ok') {
        throw 'Diagnostics verification failed.'
    }
}

$createdThumbprint = $null
$pfxPath = Join-Path ([System.IO.Path]::GetTempPath()) ('kaito-release-rehearsal-' + [guid]::NewGuid() + '.pfx')
$previousSigningTest = $env:KAITO_SIGNING_TEST
$previousCertificateBase64 = $env:WINDOWS_CERTIFICATE_BASE64
$previousCertificatePassword = $env:WINDOWS_CERTIFICATE_PASSWORD

try {
    $projectVersion = uv run --frozen python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
    if ($LASTEXITCODE -ne 0 -or $projectVersion.Trim() -ne $Version) {
        throw "Requested rehearsal version does not match pyproject.toml: requested=$Version actual=$projectVersion"
    }
    if ([string]::IsNullOrWhiteSpace($Commit)) { throw 'Rehearsal commit is required.' }
    if ($RehearsalTag -notmatch '^rehearsal-[0-9]+-[0-9]+$') { throw "Invalid rehearsal tag: $RehearsalTag" }

    Get-Content bundled/SHA256SUMS | ForEach-Object {
        if ($_ -notmatch '^([0-9a-f]{64})\s+(.+)$') { throw "Invalid bundled checksum line: $_" }
        $expected = $Matches[1]
        $name = $Matches[2].Trim()
        $path = Join-Path bundled $name
        if (-not (Test-Path $path -PathType Leaf)) { throw "Missing bundled file: $path" }
        $actual = (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) { throw "Hash mismatch for ${path}: $actual" }
        "$actual  $name" | Add-Content (Join-Path $ArtifactsDir 'bundled-sha256.txt') -Encoding ascii
    }

    $password = [Convert]::ToBase64String(
        [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(24)
    )
    $securePassword = ConvertTo-SecureString $password -AsPlainText -Force
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
    Export-PfxCertificate -Cert $certificate -FilePath $pfxPath -Password $securePassword | Out-Null

    $env:KAITO_SIGNING_TEST = '1'
    $env:WINDOWS_CERTIFICATE_PASSWORD = $password
    $env:WINDOWS_CERTIFICATE_BASE64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($pfxPath))
    Write-Output "::add-mask::$password"
    Write-Output "::add-mask::$($env:WINDOWS_CERTIFICATE_BASE64)"

    ./tools/sign_windows.ps1 `
        -Mode required `
        -ValidateOnly `
        -VerificationMode test-untrusted `
        -StatusPath (Join-Path $ArtifactsDir 'windows-signing-preflight.json')

    Invoke-CheckedNative -FailureMessage 'PyInstaller build failed.' -Action {
        uv run --frozen pyinstaller --clean --noconfirm build.spec
    }
    $executablePath = (Resolve-Path (Join-Path $DistDir 'kaito.exe')).Path
    Assert-Unsigned -Path $executablePath
    ./tools/sign_windows.ps1 `
        -Mode required `
        -FilePath $executablePath `
        -TimestampUrl '' `
        -VerificationMode test-untrusted `
        -StatusPath (Join-Path $ArtifactsDir 'windows-signing-executable.json')
    Test-SignedExecutable -ExecutablePath $executablePath

    $iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe'
    if (-not (Test-Path $iscc -PathType Leaf)) { throw "ISCC.exe not found: $iscc" }
    Invoke-CheckedNative -FailureMessage 'Inno Setup build failed.' -Action {
        & $iscc "/DMyAppVersion=$Version" 'installer/kaito.iss'
    }
    $installer = Get-ChildItem (Join-Path $DistDir 'kaito-installer-*.exe') |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $installer) { throw 'Installer output not found.' }
    $expectedInstallerName = "kaito-installer-$Version.exe"
    if ($installer.Name -ne $expectedInstallerName) {
        throw "Installer name mismatch: expected=$expectedInstallerName actual=$($installer.Name)"
    }
    Assert-Unsigned -Path $installer.FullName
    ./tools/sign_windows.ps1 `
        -Mode required `
        -FilePath $installer.FullName `
        -TimestampUrl '' `
        -VerificationMode test-untrusted `
        -StatusPath (Join-Path $ArtifactsDir 'windows-signing-installer.json')
    ./tools/test_installer.ps1 -InstallerPath $installer.FullName -ArtifactsDir $ArtifactsDir

    $sbomPath = Join-Path $DistDir 'kaito-sbom.cdx.json'
    Invoke-CheckedNative -FailureMessage 'SBOM generation failed.' -Action {
        uv run --frozen python tools/generate_sbom.py `
            --repository-root . `
            --output $sbomPath `
            --commit $Commit
    }
    Get-Content $sbomPath -Raw | ConvertFrom-Json | Out-Null

    $exeSigning = Get-Content (Join-Path $ArtifactsDir 'windows-signing-executable.json') -Raw | ConvertFrom-Json
    $installerSigning = Get-Content (Join-Path $ArtifactsDir 'windows-signing-installer.json') -Raw | ConvertFrom-Json
    if ($exeSigning.result -ne 'signed' -or $installerSigning.result -ne 'signed') {
        throw 'Both rehearsal product binaries must be signed.'
    }
    if (-not [string]::Equals(
        [string]$exeSigning.certificate.thumbprint,
        [string]$installerSigning.certificate.thumbprint,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw 'Executable and installer signer thumbprints differ.'
    }
    if (-not [string]::Equals(
        [string]$exeSigning.certificate.thumbprint,
        $createdThumbprint,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw 'Signing status does not match the generated rehearsal certificate.'
    }

    $assetPaths = @($executablePath, $installer.FullName, $sbomPath)
    $assets = foreach ($assetPath in $assetPaths) {
        $item = Get-Item $assetPath
        [ordered]@{
            name = $item.Name
            sha256 = (Get-FileHash $assetPath -Algorithm SHA256).Hash.ToLowerInvariant()
            size = $item.Length
        }
    }
    $metadata = [ordered]@{
        schema_version = 1
        rehearsal = $true
        version = $Version
        tag = $RehearsalTag
        commit = $Commit
        workflow_run = "$env:GITHUB_SERVER_URL/$env:GITHUB_REPOSITORY/actions/runs/$env:GITHUB_RUN_ID"
        signing = [ordered]@{
            mode = 'required'
            result = 'signed'
            verification_mode = 'test-untrusted'
            certificate = $exeSigning.certificate
        }
        assets = $assets
    }
    $metadataPath = Join-Path $DistDir 'RELEASE-METADATA.json'
    $metadata | ConvertTo-Json -Depth 10 | Set-Content $metadataPath -Encoding utf8

    $checksumFiles = @($executablePath, $installer.FullName, $sbomPath, $metadataPath)
    $checksumLines = foreach ($file in $checksumFiles) {
        $hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $([System.IO.Path]::GetFileName($file))"
    }
    $checksumsPath = Join-Path $DistDir 'SHA256SUMS'
    $checksumLines | Set-Content $checksumsPath -Encoding ascii

    $status = @(& git status --porcelain --untracked-files=no)
    $status | Set-Content (Join-Path $ArtifactsDir 'tracked-status.txt') -Encoding utf8
    & git diff -- . | Set-Content (Join-Path $ArtifactsDir 'tracked-diff.patch') -Encoding utf8
    if ($status.Count -gt 0) {
        $status | ForEach-Object { Write-Error "Tracked file changed during rehearsal: $_" }
        throw 'Release rehearsal mutated tracked repository files.'
    }

    $packageFiles = @($executablePath, $installer.FullName, $sbomPath, $metadataPath, $checksumsPath)
    $manifestFiles = foreach ($file in $packageFiles) {
        $item = Get-Item $file
        [ordered]@{
            name = $item.Name
            sha256 = (Get-FileHash $file -Algorithm SHA256).Hash.ToLowerInvariant()
            size = $item.Length
        }
    }
    [ordered]@{
        schema_version = 1
        version = $Version
        tag = $RehearsalTag
        commit = $Commit
        files = $manifestFiles
    } | ConvertTo-Json -Depth 8 -Compress |
        Set-Content (Join-Path $ArtifactsDir 'rehearsal-expected-manifest.json') -Encoding utf8

    $global:LASTEXITCODE = 0
}
finally {
    $env:KAITO_SIGNING_TEST = $previousSigningTest
    $env:WINDOWS_CERTIFICATE_BASE64 = $previousCertificateBase64
    $env:WINDOWS_CERTIFICATE_PASSWORD = $previousCertificatePassword
    if (-not [string]::IsNullOrWhiteSpace($createdThumbprint)) {
        Get-ChildItem "Cert:\CurrentUser\My\$createdThumbprint" -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $pfxPath -Force -ErrorAction SilentlyContinue
}
