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

$parameters = @{
    Profile = 'rehearsal'
    PackageDir = $PackageDir
    Version = $Version
    Tag = $RehearsalTag
    Commit = $Commit
    ExpectedManifestBase64 = $ExpectedManifestBase64
    ArtifactsDir = $ArtifactsDir
}
& (Join-Path $PSScriptRoot 'verify_release_package.ps1') @parameters

$global:LASTEXITCODE = 0
