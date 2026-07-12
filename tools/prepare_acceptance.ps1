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

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Invoke-SevenZip {
    param(
        [Parameter(Mandatory = $true)][string]$SevenZip,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
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

function Assert-SafeWorkRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    $marker = Join-Path $Path '.kaito-acceptance-workdir'
    if (Test-Path -LiteralPath $Path) {
        $entries = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction Stop)
        if ($entries.Count -gt 0 -and -not (Test-Path -LiteralPath $marker -PathType Leaf)) {
            throw "Refusing to reuse non-empty directory without kaito marker: $Path"
        }
        Remove-Item -LiteralPath $Path -Recurse -Force
    }

    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    Set-Content -LiteralPath $marker -Value 'Created by tools/prepare_acceptance.ps1' -Encoding utf8
}

$ArtifactRoot = Get-NormalizedPath $ArtifactRoot
$RepositoryRoot = Get-NormalizedPath $RepositoryRoot
$WorkRoot = Get-NormalizedPath $WorkRoot
$EvidenceRoot = Get-NormalizedPath $EvidenceRoot

New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
Assert-SafeWorkRoot $WorkRoot

$manifestPath = Join-Path $ArtifactRoot 'artifacts/release-sha256.txt'
$exePath = Join-Path $ArtifactRoot 'dist/kaito.exe'
$installerCandidates = @(Get-ChildItem -LiteralPath (Join-Path $ArtifactRoot 'dist') -Filter 'kaito-installer-*.exe' -File)

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Release checksum manifest is missing: $manifestPath"
}
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "kaito.exe is missing: $exePath"
}
if ($installerCandidates.Count -ne 1) {
    throw "Expected exactly one installer, found $($installerCandidates.Count) under $(Join-Path $ArtifactRoot 'dist')"
}

$installerPath = $installerCandidates[0].FullName
$artifactFiles = @{
    'kaito.exe' = $exePath
    $installerCandidates[0].Name = $installerPath
}

$verification = @()
$manifestLines = @(Get-Content -LiteralPath $manifestPath -Encoding utf8)
foreach ($line in $manifestLines) {
    if ($line -notmatch '^([0-9a-fA-F]{64})\s+(.+?)\s+(\d+)\s+bytes$') {
        throw "Invalid release manifest line: $line"
    }

    $expectedHash = $Matches[1].ToLowerInvariant()
    $name = $Matches[2]
    $expectedLength = [int64]$Matches[3]
    if (-not $artifactFiles.ContainsKey($name)) {
        throw "Manifest references an unexpected file: $name"
    }

    $path = $artifactFiles[$name]
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
        throw "Release artifact verification failed for $name"
    }
}

if ($verification.Count -ne $artifactFiles.Count) {
    throw "Manifest/file count mismatch: manifest=$($verification.Count), files=$($artifactFiles.Count)"
}

$verification | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $EvidenceRoot 'artifact-verification.json') -Encoding utf8

$sevenZip = Join-Path $RepositoryRoot 'bundled/7z.exe'
if (-not (Test-Path -LiteralPath $sevenZip -PathType Leaf)) {
    throw "Bundled 7-Zip is missing: $sevenZip"
}

$sourceRoot = Join-Path $WorkRoot 'source-data'
$nested = Join-Path $sourceRoot '日本語 と空白\深い階層\level-3'
$emptyDirectory = Join-Path $sourceRoot 'empty directory'
$previewRoot = Join-Path $sourceRoot 'preview'
$cancelRoot = Join-Path $WorkRoot 'cancel-source'
$archivesRoot = Join-Path $WorkRoot 'archives'

New-Item -ItemType Directory -Path $nested, $emptyDirectory, $previewRoot, $cancelRoot, $archivesRoot -Force | Out-Null
Set-Content -LiteralPath (Join-Path $sourceRoot 'hello.txt') -Value 'Hello from kaito acceptance test.' -Encoding utf8
Set-Content -LiteralPath (Join-Path $nested '日本語 ファイル.txt') -Value '日本語、空白、階層の保持確認。' -Encoding utf8
Set-Content -LiteralPath (Join-Path $nested 'emoji-😀.txt') -Value 'Emoji filename test.' -Encoding utf8
Set-Content -LiteralPath (Join-Path $previewRoot 'preview.txt') -Value (('0123456789abcdef' * 1024) + [Environment]::NewLine) -Encoding utf8

$pythonHelper = Join-Path $WorkRoot 'generate_acceptance_data.py'
$pythonSource = @'
from __future__ import annotations

import binascii
import hashlib
import pathlib
import struct
import sys
import zipfile
import zlib

repo = pathlib.Path(sys.argv[1]).resolve()
work = pathlib.Path(sys.argv[2]).resolve()
archives = work / "archives"
preview = work / "source-data" / "preview"
fixtures = repo / "tests" / "fixtures" / "rar"
archives.mkdir(parents=True, exist_ok=True)
preview.mkdir(parents=True, exist_ok=True)


def decode_uu(name: str, output_name: str, expected_sha256: str) -> None:
    source = fixtures / name
    lines = source.read_text(encoding="ascii").splitlines()
    if not lines or not lines[0].startswith("begin ") or lines[-1] != "end":
        raise RuntimeError(f"invalid uu fixture: {source}")
    output = bytearray()
    for line in lines[1:-1]:
        if line:
            output.extend(binascii.a2b_uu(line.encode("ascii")))
    digest = hashlib.sha256(output).hexdigest()
    if digest != expected_sha256:
        raise RuntimeError(f"RAR fixture hash mismatch: {name}: {digest} != {expected_sha256}")
    (archives / output_name).write_bytes(output)


def write_png(path: pathlib.Path, width: int = 128, height: int = 128) -> None:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend((x * 255 // (width - 1), y * 255 // (height - 1), 128))
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(bytes(raw), level=9))
    payload += chunk(b"IEND", b"")
    path.write_bytes(payload)


write_png(preview / "preview-image.png")

with zipfile.ZipFile(archives / "windows-case-collision.zip", "w") as zf:
    zf.writestr("FILE.txt", "upper")
    zf.writestr("file.txt", "lower")

with zipfile.ZipFile(archives / "duplicate-entry.zip", "w") as zf:
    zf.writestr("duplicate.txt", "first")
    zf.writestr("duplicate.txt", "second")

with zipfile.ZipFile(archives / "unsafe-windows-names.zip", "w") as zf:
    zf.writestr("CON.txt", "reserved")
    zf.writestr("folder/data.txt:secret", "alternate data stream")

(archives / "corrupt.zip").write_bytes(b"not a zip file\x00\x01\x02")
(archives / "corrupt.7z").write_bytes(b"\x00" * 100)
(archives / "corrupt.rar").write_bytes(b"Rar!\x00" + b"\x00" * 100)

decode_uu(
    "test_read_format_rar_subblock.rar.uu",
    "normal.rar",
    "e871277670529329cc2c06f178ced453c560d03fd26c76614f42ef9c06b50af0",
)
decode_uu(
    "test_read_format_rar_encryption_data.rar.uu",
    "encrypted.rar",
    "84ba9afcf0673aab0d1421d931e76a19294b12117483879c4b58598d3d71e83e",
)
decode_uu(
    "test_read_format_rar.rar.uu",
    "link-entry.rar",
    "d421b86f6290aefad61b2a36737253b2b30fe27c156bd95abfc230f24fe0307e",
)
'@
Set-Content -LiteralPath $pythonHelper -Value $pythonSource -Encoding utf8

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -ne $uv) {
    & $uv.Source run python $pythonHelper $RepositoryRoot $WorkRoot
}
else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $python) {
        throw 'Neither uv nor python was found; RAR fixtures and special ZIP files cannot be prepared.'
    }
    & $python.Source $pythonHelper $RepositoryRoot $WorkRoot
}
if ($LASTEXITCODE -ne 0) {
    throw "Acceptance data Python helper failed with exit code $LASTEXITCODE"
}
Remove-Item -LiteralPath $pythonHelper -Force

$normalZip = Join-Path $archivesRoot 'normal.zip'
$normal7z = Join-Path $archivesRoot 'normal.7z'
$encryptedZip = Join-Path $archivesRoot 'encrypted.zip'
$encrypted7z = Join-Path $archivesRoot 'encrypted.7z'
$acceptancePassword = 'Kaito-Acceptance-2026!'

Invoke-SevenZip -SevenZip $sevenZip -WorkingDirectory $sourceRoot -Arguments @('a', '-tzip', '-mx=5', $normalZip, '.\*')
Invoke-SevenZip -SevenZip $sevenZip -WorkingDirectory $sourceRoot -Arguments @('a', '-t7z', '-mx=5', $normal7z, '.\*')
Invoke-SevenZip -SevenZip $sevenZip -WorkingDirectory $sourceRoot -Arguments @('a', '-tzip', '-mem=AES256', "-p$acceptancePassword", $encryptedZip, '.\*')
Invoke-SevenZip -SevenZip $sevenZip -WorkingDirectory $sourceRoot -Arguments @('a', '-t7z', '-mhe=on', "-p$acceptancePassword", $encrypted7z, '.\*')

$largePath = Join-Path $cancelRoot "random-$LargeFileSizeMB-MiB.bin"
$buffer = New-Object byte[] (1024 * 1024)
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$stream = [System.IO.File]::Open($largePath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
try {
    for ($i = 0; $i -lt $LargeFileSizeMB; $i++) {
        $rng.GetBytes($buffer)
        $stream.Write($buffer, 0, $buffer.Length)
    }
}
finally {
    $stream.Dispose()
    $rng.Dispose()
}

$readme = @"
# kaito acceptance test data

Generated by `tools/prepare_acceptance.ps1`.

## Passwords

- `encrypted.zip`: `$acceptancePassword`
- `encrypted.7z`: `$acceptancePassword`
- `encrypted.rar`: `12345678`

These are test-only passwords and must not be replaced with personal credentials.

## Expected rejection samples

- `link-entry.rar`: contains an archive link entry and must be rejected safely.
- `windows-case-collision.zip`: contains `FILE.txt` and `file.txt` and must be rejected on Windows.
- `duplicate-entry.zip`: repeats the same internal path and must be rejected.
- `unsafe-windows-names.zip`: contains a reserved device name and an ADS-like path and must be rejected.
- `corrupt.zip`, `corrupt.7z`, `corrupt.rar`: must fail explicitly and must not be treated as empty archives.

## Cancellation source

- `cancel-source\random-$LargeFileSizeMB-MiB.bin`: use for compression cancellation.
"@
Set-Content -LiteralPath (Join-Path $WorkRoot 'TEST_DATA.md') -Value $readme -Encoding utf8

$hashLines = Get-ChildItem -LiteralPath $WorkRoot -Recurse -File |
    Where-Object { $_.Name -ne '.kaito-acceptance-workdir' } |
    Sort-Object FullName |
    ForEach-Object {
        $relative = [System.IO.Path]::GetRelativePath($WorkRoot, $_.FullName)
        "$(Get-Sha256 $_.FullName)  $relative  $($_.Length) bytes"
    }
$hashLines | Set-Content -LiteralPath (Join-Path $EvidenceRoot 'test-data-sha256.txt') -Encoding utf8

$summary = [ordered]@{
    created_at = (Get-Date).ToString('o')
    artifact_root = $ArtifactRoot
    repository_root = $RepositoryRoot
    work_root = $WorkRoot
    evidence_root = $EvidenceRoot
    manifest = $manifestPath
    executable = $exePath
    installer = $installerPath
    bundled_7zip = $sevenZip
    large_file_mib = $LargeFileSizeMB
    encrypted_zip_7z_password = $acceptancePassword
    encrypted_rar_password = '12345678'
    archives = @(Get-ChildItem -LiteralPath $archivesRoot -File | Sort-Object Name | Select-Object -ExpandProperty Name)
}
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $EvidenceRoot 'acceptance-preparation.json') -Encoding utf8

Write-Host 'Acceptance preparation completed.'
Write-Host "Work root: $WorkRoot"
Write-Host "Evidence root: $EvidenceRoot"
Write-Host "Installer: $installerPath"
