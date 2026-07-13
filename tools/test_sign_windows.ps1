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

    Write-Phase 'export PFX and trust test certificate'
    $pfxPath = Join-Path $WorkDir 'signing-test.pfx'
    $cerPath = Join-Path $WorkDir 'signing-test.cer'

    Write-Phase 'before Export-PfxCertificate'
    Export-PfxCertificate -Cert $certificate -FilePath $pfxPath -Password $securePassword | Out-Null
    Write-Phase 'after Export-PfxCertificate'

    Write-Phase 'before Export-Certificate'
    Export-Certificate -Cert $certificate -FilePath $cerPath | Out-Null
    Write-Phase 'after Export-Certificate'

    Write-Phase 'before CurrentUser\Root import'
    Import-Certificate -FilePath $cerPath -CertStoreLocation 'Cert:\CurrentUser\Root' | Out-Null
    Write-Phase 'after CurrentUser\Root import'

    Write-Phase 'before CurrentUser\TrustedPublisher import'
    Import-Certificate -FilePath $cerPath -CertStoreLocation 'Cert:\CurrentUser\TrustedPublisher' | Out-Null
    Write-Phase 'after CurrentUser\TrustedPublisher import'

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

    Write-Phase 'reject incorrect PFX password'
    $wrongPassword = [guid]::NewGuid().ToString('N')
    Invoke-ExpectedFailure -MessagePattern 'could not be opened' -Action {
        ./tools/sign_windows.ps1 `
            -Mode required `
            -ValidateOnly `
            -CertificateBase64 $certificateBase64 `
            -CertificatePassword $wrongPassword
    }

    Write-Phase 'copy executable for destructive signing test'
    $sourceExecutable = Join-Path $PSHOME 'pwsh.exe'
    if (-not (Test-Path $sourceExecutable -PathType Leaf)) {
        $sourceExecutable = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    }
    if (-not (Test-Path $sourceExecutable -PathType Leaf)) {
        throw 'No executable was available for the signing integration test.'
    }

    $testExecutable = Join-Path $WorkDir 'kaito-signing-test.exe'
    Copy-Item $sourceExecutable $testExecutable -Force
    $signedStatus = Join-Path $ArtifactsDir 'required-signed.json'
    Write-Phase 'sign and verify executable'
    ./tools/sign_windows.ps1 `
        -Mode required `
        -FilePath $testExecutable `
        -CertificateBase64 $certificateBase64 `
        -CertificatePassword $passwordText `
        -TimestampUrl '' `
        -StatusPath $signedStatus
    $signed = Get-Content $signedStatus -Raw | ConvertFrom-Json
    if ($signed.result -ne 'signed' -or $signed.files.Count -ne 1) {
        throw 'The signing integration test did not produce a signed result.'
    }

    Write-Phase 'all signing checks passed'
    @(
        'disabled: passed'
        'optional-unconfigured: passed'
        'optional-partial-config: rejected'
        'required-unconfigured: rejected'
        'malformed-base64: rejected'
        'valid-certificate-preflight: passed'
        'wrong-password: rejected'
        'sign-and-verify: passed'
    ) | Set-Content (Join-Path $ArtifactsDir 'summary.txt') -Encoding utf8
}
finally {
    Write-Phase 'cleanup test certificate and temporary files'
    if (-not [string]::IsNullOrWhiteSpace($createdThumbprint)) {
        foreach ($storeName in @('My', 'Root', 'TrustedPublisher')) {
            Get-ChildItem "Cert:\CurrentUser\$storeName\$createdThumbprint" -ErrorAction SilentlyContinue |
                Remove-Item -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
}
