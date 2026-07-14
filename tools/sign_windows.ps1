[CmdletBinding()]
param(
    [string[]]$FilePath = @(),
    [ValidateSet('disabled', 'optional', 'required')]
    [string]$Mode = $(if ([string]::IsNullOrWhiteSpace($env:WINDOWS_SIGNING_MODE)) { 'optional' } else { $env:WINDOWS_SIGNING_MODE }),
    [string]$CertificateBase64 = $env:WINDOWS_CERTIFICATE_BASE64,
    [string]$CertificatePassword = $env:WINDOWS_CERTIFICATE_PASSWORD,
    [string]$TimestampUrl = 'http://timestamp.digicert.com',
    [string]$StatusPath,
    [switch]$ValidateOnly,
    [switch]$RequireSigning,
    [ValidateSet('strict', 'test-untrusted')]
    [string]$VerificationMode = 'strict'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($RequireSigning) {
    $Mode = 'required'
}

if ($VerificationMode -eq 'test-untrusted' -and $env:KAITO_SIGNING_TEST -ne '1') {
    throw 'The test-untrusted verification mode is restricted to the signing integration test.'
}

function Write-SigningStatus {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Status
    )

    $json = $Status | ConvertTo-Json -Depth 8
    Write-Host $json
    if (-not [string]::IsNullOrWhiteSpace($StatusPath)) {
        $parent = Split-Path -Parent $StatusPath
        if (-not [string]::IsNullOrWhiteSpace($parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        $json | Set-Content -Path $StatusPath -Encoding utf8
    }
}

function Get-SignTool {
    $root = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (-not (Test-Path $root -PathType Container)) {
        throw "Windows SDK bin directory was not found: $root"
    }

    $candidates = @()
    $direct = Join-Path $root 'x64\signtool.exe'
    if (Test-Path $direct -PathType Leaf) {
        $candidates += Get-Item $direct
    }
    $candidates += @(
        Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
            ForEach-Object {
                $candidate = Join-Path $_.FullName 'x64\signtool.exe'
                if (Test-Path $candidate -PathType Leaf) {
                    Get-Item $candidate
                }
            }
    )

    $tool = $candidates |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($null -eq $tool) {
        throw 'signtool.exe was not found in the Windows SDK.'
    }
    return $tool.FullName
}

function Protect-SigningPfx {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    if ($null -eq $identity.User) {
        throw 'Unable to determine the current Windows user SID for PFX protection.'
    }
    $sid = $identity.User.Value
    $icacls = Join-Path $env:SystemRoot 'System32\icacls.exe'
    if (-not (Test-Path $icacls -PathType Leaf)) {
        throw "icacls.exe was not found: $icacls"
    }

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $aclOutput = @(
            & $icacls $Path '/inheritance:r' '/grant:r' "*${sid}:F" '/Q' 2>&1
        )
        $aclExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($aclExitCode -ne 0) {
        $details = ($aclOutput | ForEach-Object { $_.ToString() }) -join "`n"
        throw "Unable to restrict the temporary signing PFX ACL (exit code ${aclExitCode}): $details"
    }
}

$hasCertificate = -not [string]::IsNullOrWhiteSpace($CertificateBase64)
$hasPassword = -not [string]::IsNullOrWhiteSpace($CertificatePassword)

if ($Mode -eq 'disabled') {
    if ($hasCertificate -or $hasPassword) {
        Write-Warning 'Windows signing is disabled; configured certificate secrets are intentionally ignored.'
    }
    Write-SigningStatus @{
        schema_version = 1
        mode = $Mode
        result = 'unsigned'
        configured = $false
        reason = 'Signing mode is disabled.'
        files = @()
    }
    return
}

if (-not $hasCertificate -and -not $hasPassword) {
    if ($Mode -eq 'required') {
        throw 'Windows signing mode is required, but WINDOWS_CERTIFICATE_BASE64 and WINDOWS_CERTIFICATE_PASSWORD are not configured.'
    }
    Write-SigningStatus @{
        schema_version = 1
        mode = $Mode
        result = 'unsigned'
        configured = $false
        reason = 'No Windows signing certificate is configured.'
        files = @()
    }
    return
}

if (-not $hasCertificate -or -not $hasPassword) {
    throw 'Windows signing configuration is incomplete. Set both WINDOWS_CERTIFICATE_BASE64 and WINDOWS_CERTIFICATE_PASSWORD, or set WINDOWS_SIGNING_MODE=disabled.'
}

$TempDir = if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    [System.IO.Path]::GetTempPath()
}
else {
    $env:RUNNER_TEMP
}
$PfxPath = Join-Path $TempDir ('kaito-signing-' + [guid]::NewGuid() + '.pfx')

try {
    try {
        $normalizedBase64 = $CertificateBase64 -replace '\s', ''
        $pfxBytes = [Convert]::FromBase64String($normalizedBase64)
    }
    catch {
        throw 'WINDOWS_CERTIFICATE_BASE64 is not valid Base64.'
    }
    if ($pfxBytes.Length -eq 0) {
        throw 'WINDOWS_CERTIFICATE_BASE64 decoded to an empty PFX file.'
    }
    try {
        [IO.File]::WriteAllBytes($PfxPath, $pfxBytes)
        Protect-SigningPfx -Path $PfxPath
    }
    finally {
        if ($null -ne $pfxBytes) {
            [Array]::Clear($pfxBytes, 0, $pfxBytes.Length)
        }
    }

    $collection = [System.Security.Cryptography.X509Certificates.X509Certificate2Collection]::new()
    try {
        $flags = [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet
        $collection.Import($PfxPath, $CertificatePassword, $flags)
    }
    catch {
        throw 'The Windows signing PFX could not be opened. Verify that the Base64 content and password are correct.'
    }

    $now = Get-Date
    $codeSigningOid = '1.3.6.1.5.5.7.3.3'
    $eligible = @(
        $collection | Where-Object {
            $certificate = $_
            $ekuExtension = $certificate.Extensions | Where-Object {
                $_ -is [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]
            } | Select-Object -First 1
            $hasCodeSigningEku = $false
            if ($null -ne $ekuExtension) {
                $hasCodeSigningEku = @($ekuExtension.EnhancedKeyUsages | Where-Object { $_.Value -eq $codeSigningOid }).Count -gt 0
            }
            $certificate.HasPrivateKey -and
            $hasCodeSigningEku -and
            $certificate.NotBefore -le $now -and
            $certificate.NotAfter -gt $now
        }
    )

    if ($eligible.Count -eq 0) {
        throw 'The PFX does not contain a currently valid certificate with a private key and the Code Signing EKU.'
    }
    if ($eligible.Count -gt 1) {
        throw 'The PFX contains multiple eligible code-signing certificates. Provide a PFX with exactly one eligible signing certificate.'
    }

    $certificate = $eligible[0]
    if ($VerificationMode -eq 'test-untrusted') {
        $testSubject = 'CN=kaito CI signing test'
        $validityDays = ($certificate.NotAfter - $certificate.NotBefore).TotalDays
        if (
            $certificate.Subject -ne $testSubject -or
            $certificate.Issuer -ne $certificate.Subject -or
            $validityDays -gt 3
        ) {
            throw 'The test-untrusted verification mode only accepts the short-lived self-signed kaito CI test certificate.'
        }
    }

    $signTool = Get-SignTool
    $certificateInfo = @{
        subject = $certificate.Subject
        thumbprint = $certificate.Thumbprint
        not_before = $certificate.NotBefore.ToUniversalTime().ToString('o')
        not_after = $certificate.NotAfter.ToUniversalTime().ToString('o')
    }

    if ($ValidateOnly) {
        Write-SigningStatus @{
            schema_version = 1
            mode = $Mode
            result = 'ready'
            configured = $true
            reason = 'Signing certificate and SignTool validation succeeded.'
            certificate = $certificateInfo
            timestamp_url = $TimestampUrl
            pfx_file_acl = 'current-user-only'
            files = @()
        }
        return
    }

    if ($FilePath.Count -eq 0) {
        throw 'At least one -FilePath is required unless -ValidateOnly is specified.'
    }

    $signedFiles = @()
    $resolvedPaths = @()
    foreach ($Candidate in $FilePath) {
        $resolvedPaths += @(Resolve-Path $Candidate | ForEach-Object { $_.Path })
    }
    foreach ($Resolved in $resolvedPaths) {
        $Arguments = @(
            'sign',
            '/fd', 'SHA256',
            '/f', $PfxPath,
            '/p', $CertificatePassword
        )
        if (-not [string]::IsNullOrWhiteSpace($TimestampUrl)) {
            $Arguments += @('/td', 'SHA256', '/tr', $TimestampUrl)
        }
        $Arguments += $Resolved
        & $signTool @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "signtool sign failed for $Resolved with exit code $LASTEXITCODE"
        }

        $testUntrustedRootConfirmed = $false
        if ($VerificationMode -eq 'strict') {
            & $signTool 'verify' '/pa' '/all' '/v' $Resolved
            if ($LASTEXITCODE -ne 0) {
                throw "signtool verify failed for $Resolved with exit code $LASTEXITCODE"
            }
        }
        else {
            $previousErrorActionPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                $verifyLines = @(& $signTool 'verify' '/pa' '/all' '/v' $Resolved 2>&1)
                $verifyExitCode = $LASTEXITCODE
            }
            finally {
                $ErrorActionPreference = $previousErrorActionPreference
            }
            $verifyLines | ForEach-Object { Write-Host $_ }
            $verifyText = ($verifyLines | ForEach-Object { $_.ToString() }) -join "`n"
            $verifyNormalized = $verifyText -replace '\s+', ' '
            if ($verifyExitCode -ne 0) {
                $untrustedRootPattern = '(?is)(0x800B0109|CERT_E_UNTRUSTEDROOT|terminated in a root.*certificate which is not trusted by the trust provider|root certificate.*not trusted)'
                if ($verifyNormalized -notmatch $untrustedRootPattern) {
                    throw "Self-signed signtool verification failed for ${Resolved} with an unexpected error (exit code ${verifyExitCode}): $verifyText"
                }
                $testUntrustedRootConfirmed = $true
            }
        }

        $signature = Get-AuthenticodeSignature $Resolved
        if ($null -eq $signature.SignerCertificate) {
            throw "Authenticode verification found no embedded signer certificate for ${Resolved}."
        }
        if (
            -not [string]::Equals(
                $signature.SignerCertificate.Thumbprint,
                $certificate.Thumbprint,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ) {
            throw "Authenticode signer certificate does not match the configured PFX for ${Resolved}."
        }

        $signatureStatus = $signature.Status.ToString()
        if ($VerificationMode -eq 'strict') {
            if ($signatureStatus -ne 'Valid') {
                throw "Authenticode verification failed for ${Resolved}: $signatureStatus"
            }
        }
        elseif ($testUntrustedRootConfirmed) {
            if ($signatureStatus -notin @('NotTrusted', 'UnknownError')) {
                throw "Embedded Authenticode verification returned an unexpected status for ${Resolved}: $signatureStatus"
            }
        }
        elseif ($signatureStatus -ne 'Valid') {
            throw "Embedded Authenticode verification failed for ${Resolved}: $signatureStatus"
        }

        $item = Get-Item $Resolved
        $signedFiles += @{
            name = $item.Name
            sha256 = (Get-FileHash $Resolved -Algorithm SHA256).Hash.ToLowerInvariant()
            size = $item.Length
        }
        Write-Host "Signed and verified: $Resolved"
    }

    # An accepted untrusted-root result is a successful test outcome and must not leak as the caller's native exit code.
    $global:LASTEXITCODE = 0
    Write-SigningStatus @{
        schema_version = 1
        mode = $Mode
        result = 'signed'
        configured = $true
        reason = 'All requested files were signed and verified.'
        certificate = $certificateInfo
        timestamp_url = $TimestampUrl
        pfx_file_acl = 'current-user-only'
        files = $signedFiles
    }
}
finally {
    Remove-Item $PfxPath -Force -ErrorAction SilentlyContinue
}
