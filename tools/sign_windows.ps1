[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string[]]$FilePath,
    [string]$CertificateBase64 = $env:WINDOWS_CERTIFICATE_BASE64,
    [string]$CertificatePassword = $env:WINDOWS_CERTIFICATE_PASSWORD,
    [string]$TimestampUrl = 'http://timestamp.digicert.com',
    [switch]$RequireSigning
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($CertificateBase64)) {
    if ($RequireSigning) {
        throw 'WINDOWS_CERTIFICATE_BASE64 is required but was not provided.'
    }
    Write-Host 'Windows signing certificate is not configured; leaving binaries unsigned.'
    exit 0
}

$SignTool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
    Sort-Object FullName -Descending |
    Select-Object -First 1
if ($null -eq $SignTool) {
    throw 'signtool.exe was not found in the Windows SDK.'
}

$PfxPath = Join-Path $env:RUNNER_TEMP ('kaito-signing-' + [guid]::NewGuid() + '.pfx')
try {
    [IO.File]::WriteAllBytes($PfxPath, [Convert]::FromBase64String($CertificateBase64))
    foreach ($Candidate in $FilePath) {
        $Resolved = (Resolve-Path $Candidate).Path
        $Arguments = @(
            'sign',
            '/fd', 'SHA256',
            '/td', 'SHA256',
            '/tr', $TimestampUrl,
            '/f', $PfxPath
        )
        if (-not [string]::IsNullOrEmpty($CertificatePassword)) {
            $Arguments += @('/p', $CertificatePassword)
        }
        $Arguments += $Resolved
        & $SignTool.FullName @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "signtool failed for $Resolved with exit code $LASTEXITCODE"
        }
        $Signature = Get-AuthenticodeSignature $Resolved
        if ($Signature.Status -ne 'Valid') {
            throw "Authenticode verification failed for $Resolved: $($Signature.Status)"
        }
        Write-Host "Signed and verified: $Resolved"
    }
}
finally {
    Remove-Item $PfxPath -Force -ErrorAction SilentlyContinue
}
