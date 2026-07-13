[CmdletBinding()]
param(
    [string]$ArtifactsDir = 'artifacts/signing-tests'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ArtifactsDir = [System.IO.Path]::GetFullPath($ArtifactsDir)
New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null
$WorkDir = Join-Path ([System.IO.Path]::GetTempPath()) ('kaito-signing-test-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null

function Write-Phase {
    param([Parameter(Mandatory = $true)][string]$Name)
    Write-Host "[signing-test] $Name"
}

function Invoke-ExpectedFailure {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action,
        [Parameter(Mandatory = $true)]
        [string]$MessagePattern
    )

    $failed = $false
    try {
        & $Action
    }
    catch {
        $failed = $true
        if ($_.Exception.Message -notmatch $MessagePattern) {
            throw "Expected failure matching '$MessagePattern', but received: $($_.Exception.Message)"
        }
    }
    if (-not $failed) {
        throw "Expected failure matching '$MessagePattern', but the command succeeded."
    }
}

$createdThumbprint = $null
$previousSigningTestFlag = $env:KAITO_SIGNING_TEST
$env:KAITO_SIGNING_TEST = '1'
try {
    Write-Phase 'disabled mode ignores configured values'
    $ignoredSecret = [guid]::NewGuid().ToString('N')
    $disabledStatus = Join-Path $ArtifactsDir 'disabled.json'
    ./tools/sign_windows.ps1 `
        -Mode disabled `
        -ValidateOnly `
        -CertificateBase64 'not-base64' `
        -CertificatePassword $ignoredSecret `
        -StatusPath $disabledStatus
    $disabled = Get-Content $disabledStatus -Raw | ConvertFrom-Json
    if ($disabled.result -ne 'unsigned' -or $disabled.mode -ne 'disabled') {
        throw 'Disabled signing mode did not produce the expected unsigned status.'
    }

    Write-Phase 'optional mode permits no certificate'
    $optionalStatus = Join-Path $ArtifactsDir 'optional-unconfigured.json'
    ./tools/sign_windows.ps1 `
        -Mode optional `
        -ValidateOnly `
        -CertificateBase64 '' `
        -CertificatePassword '' `
        -StatusPath $optionalStatus
    $optional = Get-Content $optionalStatus -Raw | ConvertFrom-Json
    if ($optional.result -ne 'unsigned' -or $optional.configured) {
        throw 'Optional unconfigured signing mode did not produce the expected unsigned status.'
    }

    Write-Phase 'reject incomplete, required-missing, and malformed configurations'
    Invoke-ExpectedFailure -MessagePattern 'configuration is incomplete' -Action {
        ./tools/sign_windows.ps1 -Mode optional -ValidateOnly -CertificateBase64 'Zm9v' -CertificatePassword ''
    }
    Invoke-ExpectedFailure -MessagePattern 'mode is required' -Action {
        ./tools/sign_windows.ps1 -Mode required -ValidateOnly -CertificateBase64 '' -CertificatePassword ''
    }
    $malformedPfxSecret = [guid]::NewGuid().ToString('N')
    Invoke-ExpectedFailure -MessagePattern 'not valid Base64' -Action {
        ./tools/sign_windows.ps1 -Mode required -ValidateOnly -CertificateBase64 'not-base64' -CertificatePassword $malformedPfxSecret
    }

    Write-Phase 'create ephemeral code-signing certificate'
    $passwordText = [Convert]::ToBase64String(
        [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(24)
    )
    $securePassword = ConvertTo-SecureString $passwordText -AsPlainText -Force
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

    Write-Phase 'export PFX without modifying trust stores'
    $pfxPath = Join-Path $WorkDir 'signing-test.pfx'
    Write-Phase 'before Export-PfxCertificate'
    Export-PfxCertificate -Cert $certificate -FilePath $pfxPath -Password $securePassword | Out-Null
    Write-Phase 'after Export-PfxCertificate'

    Write-Phase 'validate eligible signing certificate'
    $certificateBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($pfxPath))
    $readyStatus = Join-Path $ArtifactsDir 'required-ready.json'
    ./tools/sign_windows.ps1 `
        -Mode required `
        -ValidateOnly `
        -CertificateBase64 $certificateBase64 `
        -CertificatePassword $passwordText `
        -StatusPath $readyStatus
    $ready = Get-Content $readyStatus -Raw | ConvertFrom-Json
    if ($ready.result -ne 'ready' -or -not $ready.configured) {
        throw 'A valid test certificate did not pass signing preflight.'
    }
    if ($ready.pfx_file_acl -ne 'current-user-only') {
        throw 'Signing preflight did not confirm the restricted temporary PFX ACL.'
    }

    Write-Phase 'reject incorrect PFX password'
    $wrongPassword = [guid]::NewGuid().ToString('N')
    Invoke-ExpectedFailure -MessagePattern 'could not be opened' -Action {
        ./tools/sign_windows.ps1 `
            -Mode required `
            -ValidateOnly `
            -CertificateBase64 $certificateBase64 `
            -CertificatePassword $wrongPassword
    }

    Write-Phase 'compile a fresh unsigned executable for signing'
    $compilerCandidates = @(
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
    )
    $compiler = $compilerCandidates |
        Where-Object { Test-Path $_ -PathType Leaf } |
        Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($compiler)) {
        throw 'The .NET Framework C# compiler was not available for the signing integration test.'
    }

    $sourcePath = Join-Path $WorkDir 'SigningTestProgram.cs'
    $testExecutable = Join-Path $WorkDir 'kaito-signing-test.exe'
    @'
internal static class SigningTestProgram
{
    private static int Main()
    {
        return 0;
    }
}
'@ | Set-Content $sourcePath -Encoding utf8

    & $compiler '/nologo' '/target:exe' "/out:$testExecutable" $sourcePath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $testExecutable -PathType Leaf)) {
        throw "Unable to compile the unsigned signing test executable: $LASTEXITCODE"
    }
    $unsignedSignature = Get-AuthenticodeSignature $testExecutable
    if ($unsignedSignature.Status -ne 'NotSigned') {
        throw "The freshly compiled signing target was unexpectedly signed: $($unsignedSignature.Status)"
    }

    $signedStatus = Join-Path $ArtifactsDir 'required-signed.json'
    Write-Phase 'sign and verify embedded signature without trusting the test root'
    ./tools/sign_windows.ps1 `
        -Mode required `
        -FilePath $testExecutable `
        -CertificateBase64 $certificateBase64 `
        -CertificatePassword $passwordText `
        -TimestampUrl '' `
        -StatusPath $signedStatus `
        -VerificationMode test-untrusted
    if ($LASTEXITCODE -ne 0) {
        throw "Successful test-untrusted signing leaked a native exit code: $LASTEXITCODE"
    }
    $signed = Get-Content $signedStatus -Raw | ConvertFrom-Json
    if ($signed.result -ne 'signed' -or $signed.files.Count -ne 1) {
        throw 'The signing integration test did not produce a signed result.'
    }
    if ($signed.pfx_file_acl -ne 'current-user-only') {
        throw 'Signing did not confirm the restricted temporary PFX ACL.'
    }
    if (
        -not [string]::Equals(
            [string]$signed.certificate.thumbprint,
            $createdThumbprint,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw 'The signed status certificate does not match the generated test certificate.'
    }

    Write-Phase 'independently confirm embedded signer identity'
    $embeddedSignature = Get-AuthenticodeSignature $testExecutable
    $embeddedStatus = $embeddedSignature.Status.ToString()
    # sign_windows.ps1 already required SignTool to identify the only failure as an untrusted self-signed root.
    if ($embeddedStatus -notin @('Valid', 'NotTrusted', 'UnknownError')) {
        throw "The independently inspected Authenticode signature is invalid: $embeddedStatus"
    }
    if (
        $null -eq $embeddedSignature.SignerCertificate -or
        -not [string]::Equals(
            $embeddedSignature.SignerCertificate.Thumbprint,
            $createdThumbprint,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw 'The independently inspected signer certificate does not match the generated test certificate.'
    }

    Write-Phase 'all signing checks passed'
    @(
        'disabled: passed'
        'optional-unconfigured: passed'
        'optional-partial-config: rejected'
        'required-unconfigured: rejected'
        'malformed-base64: rejected'
        'valid-certificate-preflight: passed'
        'temporary-pfx-acl: current-user-only'
        'wrong-password: rejected'
        'fresh-unsigned-pe: passed'
        'sign-and-verify: passed'
        'successful-exit-code: passed'
        'embedded-signer-thumbprint: passed'
        'trust-store-modification: not required'
    ) | Set-Content (Join-Path $ArtifactsDir 'summary.txt') -Encoding utf8
}
finally {
    Write-Phase 'cleanup test certificate and temporary files'
    $env:KAITO_SIGNING_TEST = $previousSigningTestFlag
    if (-not [string]::IsNullOrWhiteSpace($createdThumbprint)) {
        Get-ChildItem "Cert:\CurrentUser\My\$createdThumbprint" -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
}
