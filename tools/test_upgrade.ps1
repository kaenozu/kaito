[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PreviousInstallerPath,
    [Parameter(Mandatory = $true)]
    [string]$CurrentInstallerPath,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedPreviousVersion,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedCurrentVersion,
    [string]$ArtifactsDir = (Join-Path (Get-Location) 'artifacts')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$PreviousInstallerPath = (Resolve-Path $PreviousInstallerPath).Path
$CurrentInstallerPath = (Resolve-Path $CurrentInstallerPath).Path
New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null
$ArtifactsDir = (Resolve-Path $ArtifactsDir).Path

$RunRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('kaito-upgrade-e2e-' + [guid]::NewGuid())
$InstallDir = Join-Path $RunRoot 'kaito upgrade installed'
$PreviousLog = Join-Path $ArtifactsDir 'kaito-upgrade-previous-install.log'
$CurrentLog = Join-Path $ArtifactsDir 'kaito-upgrade-current-install.log'
$UninstallLog = Join-Path $ArtifactsDir 'kaito-upgrade-uninstall.log'
$PreviousVersionOutput = Join-Path $ArtifactsDir 'kaito-upgrade-previous-version.txt'
$CurrentVersionOutput = Join-Path $ArtifactsDir 'kaito-upgrade-current-version.txt'
$CurrentSelfTestOutput = Join-Path $ArtifactsDir 'kaito-upgrade-current-self-test.txt'
$SettingsPath = Join-Path $env:APPDATA 'kaito\settings.json'
$SettingsBackup = Join-Path $RunRoot 'settings.backup.json'
$SettingsExisted = Test-Path -LiteralPath $SettingsPath -PathType Leaf
$SentinelRecent = 'C:\kaito-upgrade-sentinel.zip'

$ContextKeys = @(
    'HKCU:\Software\Classes\SystemFileAssociations\.zip\shell\kaito_extract',
    'HKCU:\Software\Classes\SystemFileAssociations\.rar\shell\kaito_extract',
    'HKCU:\Software\Classes\SystemFileAssociations\.7z\shell\kaito_extract',
    'HKCU:\Software\Classes\SystemFileAssociations\.zip\shell\kaito_test',
    'HKCU:\Software\Classes\SystemFileAssociations\.rar\shell\kaito_test',
    'HKCU:\Software\Classes\SystemFileAssociations\.7z\shell\kaito_test',
    'HKCU:\Software\Classes\*\shell\kaito_compress',
    'HKCU:\Software\Classes\Directory\shell\kaito_compress'
)

function Invoke-Installer([string]$Path, [string]$LogPath) {
    $arguments = @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        '/CURRENTUSER',
        "/DIR=`"$InstallDir`"",
        "/LOG=`"$LogPath`""
    )
    $process = Start-Process -FilePath $Path -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Installer failed with exit code $($process.ExitCode): $Path"
    }
}

function Assert-Version([string]$Expected, [string]$OutputPath) {
    $exe = Join-Path $InstallDir 'kaito.exe'
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        throw "Installed executable missing: $exe"
    }
    $process = Start-Process -FilePath $exe -ArgumentList @('--version', '--output', $OutputPath) -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Installed --version failed: $($process.ExitCode)"
    }
    $actual = (Get-Content -LiteralPath $OutputPath -Raw).Trim()
    if ($actual -cne "kaito $Expected") {
        throw "Installed version mismatch: expected=kaito $Expected actual=$actual"
    }
}

function Assert-ContextCommands() {
    foreach ($key in $ContextKeys) {
        if (-not (Test-Path -LiteralPath $key)) {
            throw "Context-menu key missing after upgrade: $key"
        }
        $commandKey = Join-Path $key 'command'
        if (-not (Test-Path -LiteralPath $commandKey)) {
            throw "Context-menu command missing: $commandKey"
        }
        $command = [string](Get-Item -LiteralPath $commandKey).GetValue('')
        if ([string]::IsNullOrWhiteSpace($command) -or $command -notlike "*$InstallDir*") {
            throw "Context-menu command does not target upgraded install: $command"
        }
    }
}

try {
    New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
    if ($SettingsExisted) {
        Copy-Item -LiteralPath $SettingsPath -Destination $SettingsBackup -Force
    }
    New-Item -ItemType Directory -Path (Split-Path $SettingsPath) -Force | Out-Null
    @{
        theme = 'dark'
        language = '日本語'
        recent_files = @($SentinelRecent)
        check_updates = $false
    } | ConvertTo-Json | Set-Content -LiteralPath $SettingsPath -Encoding utf8

    Invoke-Installer $PreviousInstallerPath $PreviousLog
    Assert-Version $ExpectedPreviousVersion $PreviousVersionOutput

    Invoke-Installer $CurrentInstallerPath $CurrentLog
    Assert-Version $ExpectedCurrentVersion $CurrentVersionOutput
    Assert-ContextCommands

    $settings = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
    if ([string]$settings.theme -cne 'dark') {
        throw 'Theme setting was not preserved across upgrade.'
    }
    if (@($settings.recent_files).Count -ne 1 -or [string]$settings.recent_files[0] -cne $SentinelRecent) {
        throw 'Recent-file sentinel was not preserved across upgrade.'
    }

    $exe = Join-Path $InstallDir 'kaito.exe'
    $selfTest = Start-Process -FilePath $exe -ArgumentList @('--self-test', '--output', $CurrentSelfTestOutput) -Wait -PassThru
    if ($selfTest.ExitCode -ne 0) {
        throw "Upgraded self-test failed: $($selfTest.ExitCode)"
    }
    if ((Get-Content -LiteralPath $CurrentSelfTestOutput -Raw) -notmatch 'All checks passed') {
        throw 'Upgraded self-test did not report success.'
    }

    $uninstaller = Join-Path $InstallDir 'unins000.exe'
    if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
        throw 'Upgraded uninstaller is missing.'
    }
    $uninstall = Start-Process -FilePath $uninstaller -ArgumentList @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        "/LOG=`"$UninstallLog`""
    ) -Wait -PassThru
    if ($uninstall.ExitCode -ne 0) {
        throw "Upgrade uninstall failed: $($uninstall.ExitCode)"
    }
    Start-Sleep -Seconds 2

    foreach ($key in $ContextKeys) {
        if (Test-Path -LiteralPath $key) {
            throw "Context-menu key remained after upgraded uninstall: $key"
        }
    }
    if (-not (Test-Path -LiteralPath $SettingsPath -PathType Leaf)) {
        throw 'User settings were unexpectedly deleted by uninstall.'
    }

    Write-Host "Upgrade E2E passed: $ExpectedPreviousVersion -> $ExpectedCurrentVersion"
}
finally {
    foreach ($key in $ContextKeys) {
        Remove-Item -LiteralPath $key -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($SettingsExisted -and (Test-Path -LiteralPath $SettingsBackup -PathType Leaf)) {
        New-Item -ItemType Directory -Path (Split-Path $SettingsPath) -Force | Out-Null
        Copy-Item -LiteralPath $SettingsBackup -Destination $SettingsPath -Force
    }
    elseif (-not $SettingsExisted) {
        Remove-Item -LiteralPath $SettingsPath -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $RunRoot -Recurse -Force -ErrorAction SilentlyContinue
}
