[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ArtifactRoot,

    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),

    [string]$WorkRoot = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'kaito 受け入れテスト'),

    [string]$EvidenceRoot = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'kaito-acceptance-evidence'),

    [ValidateRange(1, 4096)]
    [int]$LargeFileSizeMB = 128
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Reset-WorkRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    $marker = Join-Path $Path '.kaito-acceptance-workdir'
    if (Test-Path -LiteralPath $Path) {
        $entries = @(Get-ChildItem -LiteralPath $Path -Force)
        if ($entries.Count -gt 0 -and -not (Test-Path -LiteralPath $marker -PathType Leaf)) {
            throw "Refusing to reuse non-empty directory without kaito marker: $Path"
        }
        Remove-Item -LiteralPath $Path -Recurse -Force
    }

    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    Set-Content -LiteralPath $marker -Value 'Created by tools/prepare_acceptance.ps1' -Encoding utf8
}

function Invoke-SevenZip {
    param(
        [Parameter(Mandatory = $true)][string]$SevenZip,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    Push-Location $WorkingDirectory
    try {
        $output = & $SevenZip @Arguments '-y' '-sccUTF-8' 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "7-Zip failed with exit code $LASTEXITCODE.`n$($output -join [Environment]::NewLine)"
        }
    }
    finally {
        Pop-Location
    }
}

$ArtifactRoot = Get-FullPath $ArtifactRoot
$RepositoryRoot = Get-FullPath $RepositoryRoot
$WorkRoot = Get-FullPath $WorkRoot
$EvidenceRoot = Get-FullPath $EvidenceRoot

New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
Reset-WorkRoot $WorkRoot

$manifestPath = Join-Path $ArtifactRoot 'artifacts/build-sha256.txt'
$exePath = Join-Path $ArtifactRoot 'dist/kaito.exe'
$installerCandidates = @(
    Get-ChildItem -LiteralPath (Join-Path $ArtifactRoot 'dist') -Filter 'kaito-installer-*.exe' -File
)

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Build checksum manifest is missing: $manifestPath"
}
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "kaito.exe is missing: $exePath"
}
if ($installerCandidates.Count -ne 1) {
    throw "Expected exactly one installer, found $($installerCandidates.Count)"
}

$installerPath = $installerCandidates[0].FullName
$artifactFiles = @{}
$artifactFiles['kaito.exe'] = $exePath
$artifactFiles[$installerCandidates[0].Name] = $installerPath

$verification = @()
foreach ($line in Get-Content -LiteralPath $manifestPath -Encoding utf8) {
    if ($line -notmatch '^([0-9a-fA-F]{64})\s+(.+?)\s+(\d+)\s+bytes$') {
        throw "Invalid build manifest line: $line"
    }

    $expectedHash = $Matches[1].ToLowerInvariant()
    $name = $Matches[2]
    $expectedLength = [int64]$Matches[3]
    if (-not $artifactFiles.ContainsKey($name)) {
        throw "Manifest references an unexpected file: $name"
    }

    $path = [string]$artifactFiles[$name]
    $actualHash = Get-Sha256 $path
    $actualLength = (Get-Item -LiteralPath $path).Length
    $ok = $actualHash -eq $expectedHash -and $actualLength -eq $expectedLength
    $verification += [ordered]@{
        file = $name
        path = $path
        expected_sha256 = $expectedHash
        actual_sha256 = $actualHash
        expected_bytes = $expectedLength
        actual_bytes = $actualLength
        ok = $ok
    }
    if (-not $ok) {
        throw "Build artifact verification failed for $name"
    }
}

if ($verification.Count -ne $artifactFiles.Count) {
    throw "Manifest/file count mismatch: manifest=$($verification.Count), files=$($artifactFiles.Count)"
}

$verification |
    ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath (Join-Path $EvidenceRoot 'artifact-verification.json') -Encoding utf8

$generator = Join-Path $RepositoryRoot 'tools/generate_acceptance_data.py'
if (-not (Test-Path -LiteralPath $generator -PathType Leaf)) {
    throw "Acceptance generator is missing: $generator"
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -ne $uv) {
    & $uv.Source run --frozen python $generator `
        --repo-root $RepositoryRoot `
        --work-root $WorkRoot `
        --large-file-size-mib $LargeFileSizeMB
}
else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $python) {
        throw 'Neither uv nor python was found.'
    }
    & $python.Source $generator `
        --repo-root $RepositoryRoot `
        --work-root $WorkRoot `
        --large-file-size-mib $LargeFileSizeMB
}
if ($LASTEXITCODE -ne 0) {
    throw "Acceptance generator failed with exit code $LASTEXITCODE"
}

$sevenZip = Join-Path $RepositoryRoot 'bundled/7z.exe'
if (-not (Test-Path -LiteralPath $sevenZip -PathType Leaf)) {
    throw "Bundled 7-Zip is missing: $sevenZip"
}

$sourceRoot = Join-Path $WorkRoot 'source-data'
$archivesRoot = Join-Path $WorkRoot 'archives'
$password = 'Kaito-Acceptance-2026!'

Invoke-SevenZip -SevenZip $sevenZip -WorkingDirectory $sourceRoot -Arguments @(
    'a', '-tzip', '-mx=5', (Join-Path $archivesRoot 'normal.zip'), '.\*'
)
Invoke-SevenZip -SevenZip $sevenZip -WorkingDirectory $sourceRoot -Arguments @(
    'a', '-t7z', '-mx=5', (Join-Path $archivesRoot 'normal.7z'), '.\*'
)
Invoke-SevenZip -SevenZip $sevenZip -WorkingDirectory $sourceRoot -Arguments @(
    'a', '-tzip', '-mem=AES256', "-p$password", (Join-Path $archivesRoot 'encrypted.zip'), '.\*'
)
Invoke-SevenZip -SevenZip $sevenZip -WorkingDirectory $sourceRoot -Arguments @(
    'a', '-t7z', '-mhe=on', "-p$password", (Join-Path $archivesRoot 'encrypted.7z'), '.\*'
)

$readme = @"
# kaito acceptance test data

Generated by tools/prepare_acceptance.ps1.

## Test-only passwords

- encrypted.zip: $password
- encrypted.7z: $password
- encrypted.rar: 12345678

## Expected rejection samples

- link-entry.rar
- windows-case-collision.zip
- duplicate-entry.zip
- unsafe-windows-names.zip
- corrupt.zip
- corrupt.7z
- corrupt.rar

The passwords above are test data. Do not replace them with personal credentials.
"@
Set-Content -LiteralPath (Join-Path $WorkRoot 'TEST_DATA.md') -Value $readme -Encoding utf8

$hashLines = Get-ChildItem -LiteralPath $WorkRoot -Recurse -File |
    Where-Object { $_.Name -ne '.kaito-acceptance-workdir' } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($WorkRoot.Length).TrimStart('\')
        "$(Get-Sha256 $_.FullName)  $relative  $($_.Length) bytes"
    }
$hashLines | Set-Content -LiteralPath (Join-Path $EvidenceRoot 'test-data-sha256.txt') -Encoding utf8

$summary = [ordered]@{
    created_at = (Get-Date).ToString('o')
    artifact_root = $ArtifactRoot
    repository_root = $RepositoryRoot
    work_root = $WorkRoot
    evidence_root = $EvidenceRoot
    executable = $exePath
    installer = $installerPath
    bundled_7zip = $sevenZip
    large_file_mib = $LargeFileSizeMB
    encrypted_zip_7z_password = $password
    encrypted_rar_password = '12345678'
    archives = @(
        Get-ChildItem -LiteralPath $archivesRoot -File |
            Sort-Object Name |
            Select-Object -ExpandProperty Name
    )
}
$summary |
    ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath (Join-Path $EvidenceRoot 'acceptance-preparation.json') -Encoding utf8

Write-Host 'Acceptance preparation completed.'
Write-Host "Work root: $WorkRoot"
Write-Host "Evidence root: $EvidenceRoot"
Write-Host "Installer: $installerPath"
