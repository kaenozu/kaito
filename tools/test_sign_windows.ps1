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
    $disabledStatus = Join-Path $ArtifactsDir 'disabled.json'
    ./tools/sign_windows.ps1 `
        -Mode disabled `
        -ValidateOnly `
        -CertificateBase64 'not-base64' `
        -CertificatePassword 'ignored' `
        -StatusPath $disabledStatus
    $disabled = Get-Content $disabledStatus -Raw | ConvertFrom-Json
    if ($disabled.result -ne 'unsigned' -or $disabled.mode -ne 'disabled') {
        throw 'Disabled signing mode did not produce the expected unsigned status.'
    }

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

    Invoke-ExpectedFailure -MessagePattern 'configuration is incomplete' -Action {
        ./tools/sign_windows.ps1 -Mode optional -ValidateOnly -CertificateBase64 'Zm9v' -CertificatePassword ''
    }
    Invoke-ExpectedFailure -MessagePattern 'mode is required' -Action {
        ./tools/sign_windows.ps1 -Mode required -ValidateOnly -CertificateBase64 '' -CertificatePassword ''
    }
    Invoke-ExpectedFailure -MessagePattern 'not valid Base64' -Action {
        ./tools/sign_windows.ps1 -Mode required -ValidateOnly -CertificateBase64 'not-base64' -CertificatePassword 'password'
    }

    $passwordText = 'kaito-ci-signing-test'
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

    $pfxPath = Join-Path $WorkDir 'signing-test.pfx'
    $cerPath = Join-Path $WorkDir 'signing-test.cer'
    Export-PfxCertificate -Cert $certificate -FilePath $pfxPath -Password $securePassword | Out-Null
    Export-Certificate -Cert $certificate -FilePath $cerPath | Out-Null
    Import-Certificate -FilePath $cerPath -CertStoreLocation 'Cert:\CurrentUser\Root' | Out-Null
    Import-Certificate -FilePath $cerPath -CertStoreLocation 'Cert:\CurrentUser\TrustedPublisher' | Out-Null

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

    Invoke-ExpectedFailure -MessagePattern 'could not be opened' -Action {
        ./tools/sign_windows.ps1 `
            -Mode required `
            -ValidateOnly `
            -CertificateBase64 $certificateBase64 `
            -CertificatePassword 'wrong-password'
    }

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
    if (-not [string]::IsNullOrWhiteSpace($createdThumbprint)) {
        foreach ($storeName in @('My', 'Root', 'TrustedPublisher')) {
            Get-ChildItem "Cert:\CurrentUser\$storeName\$createdThumbprint" -ErrorAction SilentlyContinue |
                Remove-Item -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item $WorkDir -Recurse -Force -ErrorAction SilentlyContinue
}
