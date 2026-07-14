[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Tag,
    [Parameter(Mandatory = $true)]
    [string]$Commit,
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [Parameter(Mandatory = $true)]
    [string[]]$AssetPaths,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($env:GH_TOKEN)) {
    throw 'GH_TOKEN is required.'
}
if ([string]::IsNullOrWhiteSpace($env:GITHUB_API_URL)) {
    throw 'GITHUB_API_URL is required.'
}
if ([string]::IsNullOrWhiteSpace($env:GITHUB_REPOSITORY)) {
    throw 'GITHUB_REPOSITORY is required.'
}
if ($Tag -cne "v$Version") {
    throw "Tag/version mismatch: tag=$Tag version=$Version"
}
if ($Commit -cnotmatch '^[0-9a-f]{40}$') {
    throw 'Commit must be a lowercase 40-character SHA.'
}
if ($AssetPaths.Count -ne 5) {
    throw "Exactly five release assets are required, received $($AssetPaths.Count)."
}

$resolvedAssets = @()
$seenNames = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
foreach ($assetPath in $AssetPaths) {
    $resolved = (Resolve-Path $assetPath).Path
    $item = Get-Item $resolved
    if (-not $item.PSIsContainer -and $seenNames.Add($item.Name)) {
        $resolvedAssets += $item
    }
    else {
        throw "Release asset is not a unique file: $assetPath"
    }
}

$headers = @{
    Authorization = "Bearer $env:GH_TOKEN"
    Accept = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
}
$releaseByTagUri = "$env:GITHUB_API_URL/repos/$env:GITHUB_REPOSITORY/releases/tags/$Tag"
$existing = $null
try {
    $existing = Invoke-RestMethod -Method Get -Uri $releaseByTagUri -Headers $headers
}
catch {
    if ($null -eq $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 404) {
        throw
    }
}
if ($null -ne $existing) {
    throw "Release $Tag already exists (id=$($existing.id), draft=$($existing.draft)). Existing Releases are never reused or overwritten."
}

$createUri = "$env:GITHUB_API_URL/repos/$env:GITHUB_REPOSITORY/releases"
$payload = @{
    tag_name = $Tag
    target_commitish = $Commit
    name = "kaito v$Version"
    draft = $true
    prerelease = $false
    generate_release_notes = $true
} | ConvertTo-Json

try {
    $release = Invoke-RestMethod `
        -Method Post `
        -Uri $createUri `
        -Headers $headers `
        -ContentType 'application/json' `
        -Body $payload
}
catch {
    throw "Unable to create a new Draft Release. Existing Releases are never reused: $($_.Exception.Message)"
}

if (-not [bool]$release.draft) {
    throw 'Newly created Release is not draft.'
}
if ([string]$release.tag_name -cne $Tag) {
    throw "Created Release tag mismatch: $($release.tag_name)"
}
if ([string]$release.target_commitish -cne $Commit) {
    throw "Created Release target mismatch: $($release.target_commitish)"
}

$uploadTemplate = [string]$release.upload_url
$uploadBase = $uploadTemplate -replace '\{\?name,label\}$', ''
$uploadedAssetIds = @()
try {
    foreach ($asset in $resolvedAssets) {
        $encodedName = [Uri]::EscapeDataString($asset.Name)
        $uploadUri = "$uploadBase?name=$encodedName"
        $uploaded = Invoke-RestMethod `
            -Method Post `
            -Uri $uploadUri `
            -Headers $headers `
            -ContentType 'application/octet-stream' `
            -InFile $asset.FullName
        if ([string]$uploaded.name -cne $asset.Name) {
            throw "Uploaded asset name mismatch: expected=$($asset.Name) actual=$($uploaded.name)"
        }
        $uploadedAssetIds += [string]$uploaded.id
    }
}
catch {
    throw "Draft Release $($release.id) was created but asset upload failed. Leave it in Draft for investigation and do not reuse it: $($_.Exception.Message)"
}

$resolvedRelease = Invoke-RestMethod -Method Get -Uri $releaseByTagUri -Headers $headers
if ([string]$resolvedRelease.id -cne [string]$release.id) {
    throw "Release lookup did not resolve the newly created Release: created=$($release.id) resolved=$($resolvedRelease.id)"
}
if (-not [bool]$resolvedRelease.draft) {
    throw 'Release became public during asset upload.'
}
if (@($resolvedRelease.assets).Count -ne 5) {
    throw "Draft Release asset count mismatch: $(@($resolvedRelease.assets).Count)"
}

$actualNames = @($resolvedRelease.assets | ForEach-Object { [string]$_.name } | Sort-Object)
$expectedNames = @($resolvedAssets | ForEach-Object { $_.Name } | Sort-Object)
if (Compare-Object $expectedNames $actualNames) {
    throw "Draft Release asset names differ from the verified build set: expected=$($expectedNames -join ',') actual=$($actualNames -join ',')"
}

@(
    "id=$($release.id)"
    "html_url=$($release.html_url)"
) | Out-File $OutputPath -Append

Write-Host "Created new Draft Release $($release.id) for $Tag with five verified asset names."
