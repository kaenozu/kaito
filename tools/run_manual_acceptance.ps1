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

$RepositoryRoot = [System.IO.Path]::GetFullPath($RepositoryRoot)
$ArtifactRoot = [System.IO.Path]::GetFullPath($ArtifactRoot)
$WorkRoot = [System.IO.Path]::GetFullPath($WorkRoot)
$EvidenceRoot = [System.IO.Path]::GetFullPath($EvidenceRoot)

$prepare = Join-Path $RepositoryRoot 'tools/prepare_acceptance.ps1'
$collect = Join-Path $RepositoryRoot 'tools/collect_acceptance_evidence.ps1'
$checklist = Join-Path $RepositoryRoot 'docs/GUI_ACCEPTANCE.md'

foreach ($path in @($prepare, $collect)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required script is missing: $path"
    }
}

Write-Host '=== [1/4] 受け入れデータの準備 ==='
& $prepare -ArtifactRoot $ArtifactRoot -RepositoryRoot $RepositoryRoot -WorkRoot $WorkRoot -EvidenceRoot $EvidenceRoot -LargeFileSizeMB $LargeFileSizeMB
if ($LASTEXITCODE -ne 0) { throw "prepare_acceptance.ps1 failed with exit code $LASTEXITCODE" }

Write-Host ''
Write-Host '=== [2/4] Before エビデンスの収集 ==='
& $collect -Phase Before -RepositoryRoot $RepositoryRoot -EvidenceRoot $EvidenceRoot -WorkRoot $WorkRoot
if ($LASTEXITCODE -ne 0) { throw "collect_acceptance_evidence.ps1 (Before) failed with exit code $LASTEXITCODE" }

$prep = Get-Content -LiteralPath (Join-Path $EvidenceRoot 'acceptance-preparation.json') -Raw | ConvertFrom-Json
$exe = [string]$prep.executable

Write-Host ''
Write-Host '=== [3/4] 手動 GUI 確認 ==='
Write-Host "チェックリスト: $checklist"
Write-Host "テストデータ: $WorkRoot (TEST_DATA.md にパスワード)"
Write-Host "エビデンス:   $EvidenceRoot"
Write-Host ''
Write-Host 'kaito を起動します。チェックリストの項目を確認してください。'
Start-Process -FilePath $exe
Write-Host ''
$null = Read-Host '確認が完了し kaito をすべて閉じたら、Enter を押してください'

Write-Host ''
Write-Host '=== [4/4] After エビデンスの収集 ==='
& $collect -Phase After -RepositoryRoot $RepositoryRoot -EvidenceRoot $EvidenceRoot -WorkRoot $WorkRoot
$afterExit = $LASTEXITCODE

Write-Host ''
Write-Host "After エビデンス: $(Join-Path $EvidenceRoot 'environment-after.json')"
if ($afterExit -eq 0) {
    Write-Host '後片付けチェック: PASS（kaito / 7z プロセスの残存なし）'
}
else {
    Write-Error '後片付けチェック: FAIL（kaito が起動中の可能性があります。閉じてから collect_acceptance_evidence.ps1 -Phase After を再実行してください）'
}
exit $afterExit
