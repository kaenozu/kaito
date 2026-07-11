[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,
    [string]$ArtifactsDir = (Join-Path (Get-Location) 'artifacts')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$InstallerPath = (Resolve-Path $InstallerPath).Path
New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null
$ArtifactsDir = (Resolve-Path $ArtifactsDir).Path

$RunRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('kaito-installer-e2e-' + [guid]::NewGuid())
$InstallDir = Join-Path $RunRoot 'kaito 検証 installed'
$InstallLog = Join-Path $ArtifactsDir 'kaito-install.log'
$UninstallLog = Join-Path $ArtifactsDir 'kaito-uninstall.log'
$SelfTestOutput = Join-Path $ArtifactsDir 'kaito-installed-self-test.txt'
$BackendOutput = Join-Path $ArtifactsDir 'kaito-installed-backend.json'

$ExtractKeys = @('.zip', '.rar', '.7z') | ForEach-Object {
    "HKCU:\Software\Classes\SystemFileAssociations\$_\shell\kaito_extract"
}
$CompressKeys = @(
    'HKCU:\Software\Classes\*\shell\kaito_compress',
    'HKCU:\Software\Classes\Directory\shell\kaito_compress'
)

try {
    New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
    $InstallArguments = @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        '/CURRENTUSER',
        "/DIR=`"$InstallDir`"",
        "/LOG=`"$InstallLog`""
    )
    $InstallProcess = Start-Process -FilePath $InstallerPath -ArgumentList $InstallArguments -Wait -PassThru
    if ($InstallProcess.ExitCode -ne 0) {
        throw "Installer failed with exit code $($InstallProcess.ExitCode)"
    }

    $InstalledExe = Join-Path $InstallDir 'kaito.exe'
    $RequiredFiles = @(
        $InstalledExe,
        (Join-Path $InstallDir 'LICENSE'),
        (Join-Path $InstallDir 'SECURITY.md'),
        (Join-Path $InstallDir 'THIRD_PARTY_NOTICES.md'),
        (Join-Path $InstallDir 'licenses\7-ZIP-LICENSE.txt'),
        (Join-Path $InstallDir 'licenses\SHA256SUMS'),
        (Join-Path $InstallDir 'licenses\SOURCE-PACKAGE.txt')
    )
    foreach ($RequiredFile in $RequiredFiles) {
        if (-not (Test-Path $RequiredFile -PathType Leaf)) {
            throw "Installed file missing: $RequiredFile"
        }
    }

    $SelfTestProcess = Start-Process -FilePath $InstalledExe -ArgumentList @('--self-test', '--output', $SelfTestOutput) -Wait -PassThru
    if ($SelfTestProcess.ExitCode -ne 0) {
        throw "Installed self-test failed with exit code $($SelfTestProcess.ExitCode)"
    }
    $SelfTest = Get-Content $SelfTestOutput -Raw
    if ($SelfTest -notmatch 'All checks passed') {
        throw "Installed self-test did not report success: $SelfTest"
    }

    $BackendProcess = Start-Process -FilePath $InstalledExe -ArgumentList @('--backend-info', '--json', '--output', $BackendOutput) -Wait -PassThru
    if ($BackendProcess.ExitCode -ne 0) {
        throw "Installed backend-info failed with exit code $($BackendProcess.ExitCode)"
    }
    $BackendInfo = Get-Content $BackendOutput -Raw | ConvertFrom-Json
    if (-not $BackendInfo.available) { throw 'Bundled backend is unavailable after installation' }
    if ($BackendInfo.source -ne 'bundled') { throw "Unexpected backend source: $($BackendInfo.source)" }
    if ($BackendInfo.version -ne '26.02') { throw "Unexpected bundled 7-Zip version: $($BackendInfo.version)" }
    if ($BackendInfo.integrity -ne 'ok' -or $BackendInfo.sha256 -ne $BackendInfo.expected_sha256) {
        throw 'Bundled backend integrity validation failed after installation'
    }

    foreach ($Key in ($ExtractKeys + $CompressKeys)) {
        if (-not (Test-Path $Key)) { throw "Context-menu key missing: $Key" }
    }
    if (Test-Path 'HKCU:\Software\Classes\SystemFileAssociations\.txt\shell\kaito_extract') {
        throw 'Extract action must not be registered for unsupported .txt files'
    }

    $Uninstaller = Join-Path $InstallDir 'unins000.exe'
    if (-not (Test-Path $Uninstaller -PathType Leaf)) {
        throw "Uninstaller missing: $Uninstaller"
    }
    $UninstallArguments = @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        "/LOG=`"$UninstallLog`""
    )
    $UninstallProcess = Start-Process -FilePath $Uninstaller -ArgumentList $UninstallArguments -Wait -PassThru
    if ($UninstallProcess.ExitCode -ne 0) {
        throw "Uninstaller failed with exit code $($UninstallProcess.ExitCode)"
    }
    Start-Sleep -Seconds 2

    foreach ($Key in ($ExtractKeys + $CompressKeys)) {
        if (Test-Path $Key) { throw "Context-menu key remained after uninstall: $Key" }
    }
    if (Test-Path $InstallDir) {
        $Remaining = @(Get-ChildItem $InstallDir -Force -ErrorAction SilentlyContinue)
        if ($Remaining.Count -gt 0) {
            throw "Install directory was not cleaned: $InstallDir"
        }
    }

    Write-Host 'Installer lifecycle E2E passed.'
    Write-Host "Install log: $InstallLog"
    Write-Host "Uninstall log: $UninstallLog"
}
finally {
    foreach ($Key in ($ExtractKeys + $CompressKeys)) {
        Remove-Item $Key -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $RunRoot -Recurse -Force -ErrorAction SilentlyContinue
}
