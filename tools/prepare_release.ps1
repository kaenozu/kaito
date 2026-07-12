[CmdletBinding()]
param(
    [string]$Repository = 'kaenozu/kaito',
    [switch]$AllowExistingTag
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectVersion = uv run --frozen python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
if ($LASTEXITCODE -ne 0) { throw 'Unable to read the project version.' }
$ProjectVersion = $ProjectVersion.Trim()
$Tag = "v$ProjectVersion"

if ($ProjectVersion -match '(dev|a|b|rc)') {
    throw "Stable release preflight refuses prerelease version: $ProjectVersion"
}

if (-not (Select-String -Path CHANGELOG.md -Pattern ([regex]::Escape("[$ProjectVersion]")) -Quiet)) {
    throw "CHANGELOG.md does not contain a [$ProjectVersion] section."
}

$RemoteTag = git ls-remote --tags origin "refs/tags/$Tag"
if ($LASTEXITCODE -ne 0) { throw 'Unable to query remote tags.' }
if (-not [string]::IsNullOrWhiteSpace($RemoteTag) -and -not $AllowExistingTag) {
    throw "Tag $Tag already exists. Never move an existing release tag; bump the version instead."
}

$Status = @(git status --porcelain)
if ($Status.Count -gt 0) {
    throw 'Working tree is not clean.'
}

$Branch = git branch --show-current
if ($Branch -ne 'master') {
    Write-Warning "Release preflight is running from '$Branch', not master."
}

Write-Host 'Release preflight passed.'
Write-Host "Repository: $Repository"
Write-Host "Version: $ProjectVersion"
Write-Host "Tag: $Tag"
Write-Host "Next step after CI and approval: git tag -a $Tag -m 'kaito $ProjectVersion'; git push origin $Tag"
