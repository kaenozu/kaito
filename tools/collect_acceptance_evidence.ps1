[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Before', 'After')]
    [string]$Phase,

    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),

    [string]$EvidenceRoot = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'kaito-acceptance-evidence'),

    [string]$InstallPath = '',

    [string]$WorkRoot = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'kaito 受け入れテスト')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-RegistrySnapshot {
    $keys = @(
        'HKCU:\Software\Classes\SystemFileAssociations\.zip\shell\kaito_extract',
        'HKCU:\Software\Classes\SystemFileAssociations\.rar\shell\kaito_extract',
        'HKCU:\Software\Classes\SystemFileAssociations\.7z\shell\kaito_extract',
        'HKCU:\Software\Classes\*\shell\kaito_compress',
        'HKCU:\Software\Classes\Directory\shell\kaito_compress',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{B8F4C3D2-E1A0-4F6B-9C8D-7E5A3B2C1D0F}_is1'
    )

    return @($keys | ForEach-Object {
        [ordered]@{
            path = $_
            exists = Test-Path -LiteralPath $_
            values = if (Test-Path -LiteralPath $_) {
                try {
                    Get-ItemProperty -LiteralPath $_ | Select-Object *
                }
                catch {
                    [ordered]@{ error = $_.Exception.Message }
                }
            }
            else {
                $null
            }
        }
    })
}

function Get-ProcessSnapshot {
    $processes = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @('kaito.exe', '7z.exe')
    })

    return @($processes | ForEach-Object {
        [ordered]@{
            name = $_.Name
            process_id = $_.ProcessId
            parent_process_id = $_.ParentProcessId
            executable_path = $_.ExecutablePath
            command_line = if ($_.CommandLine -match '(?i)(?:-p|--password(?:=|\s+))[^\s"]+') {
                [regex]::Replace($_.CommandLine, '(?i)(?:-p|--password(?:=|\s+))[^\s"]+', '-p***')
            }
            else {
                $_.CommandLine
            }
            creation_date = $_.CreationDate
        }
    })
}

function Get-DisplaySnapshot {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        return @([System.Windows.Forms.Screen]::AllScreens | ForEach-Object {
            [ordered]@{
                device_name = $_.DeviceName
                primary = $_.Primary
                bounds = $_.Bounds.ToString()
                working_area = $_.WorkingArea.ToString()
            }
        })
    }
    catch {
        return @([ordered]@{ error = $_.Exception.Message })
    }
}

function Get-GitSnapshot {
    param([string]$Root)

    if (-not (Test-Path -LiteralPath (Join-Path $Root '.git'))) {
        return [ordered]@{ available = $false }
    }

    $branch = (& git -C $Root branch --show-current 2>$null) -join "`n"
    $head = (& git -C $Root rev-parse HEAD 2>$null) -join "`n"
    $status = (& git -C $Root status --short 2>$null) -join "`n"
    return [ordered]@{
        available = $true
        branch = $branch.Trim()
        head = $head.Trim()
        status_short = $status
    }
}

function Get-TempSnapshot {
    $temp = [System.IO.Path]::GetTempPath()
    return @(
        Get-ChildItem -LiteralPath $temp -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like '_MEI*' -or $_.Name -like '*kaito*' } |
            Select-Object Name, FullName, PSIsContainer, Length, LastWriteTime
    )
}

function Get-DeveloperModeState {
    $path = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'
    if (-not (Test-Path -LiteralPath $path)) {
        return $false
    }
    return (Get-ItemPropertyValue -LiteralPath $path -Name AllowDevelopmentWithoutDevLicense -ErrorAction SilentlyContinue) -eq 1
}

function Get-DisplayDpi {
    $paths = @(
        'HKCU:\Control Panel\Desktop\WindowMetrics',
        'HKCU:\Control Panel\Desktop'
    )
    foreach ($path in $paths) {
        if (Test-Path -LiteralPath $path) {
            foreach ($name in @('AppliedDPI', 'LogPixels')) {
                $value = Get-ItemPropertyValue -LiteralPath $path -Name $name -ErrorAction SilentlyContinue
                if ($null -ne $value) {
                    return [ordered]@{
                        registry_path = $path
                        value_name = $name
                        dpi = [int]$value
                        scale_percent = [math]::Round(([int]$value / 96.0) * 100)
                    }
                }
            }
        }
    }
    return [ordered]@{ dpi = $null; scale_percent = $null }
}

$RepositoryRoot = [System.IO.Path]::GetFullPath($RepositoryRoot)
$EvidenceRoot = [System.IO.Path]::GetFullPath($EvidenceRoot)
$WorkRoot = [System.IO.Path]::GetFullPath($WorkRoot)
if ($InstallPath) {
    $InstallPath = [System.IO.Path]::GetFullPath($InstallPath)
}

New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null

$os = Get-CimInstance Win32_OperatingSystem
$computer = Get-CimInstance Win32_ComputerSystem
$systemSevenZip = @(
    Get-Command 7z.exe -All -ErrorAction SilentlyContinue | Select-Object Name, Source, Version
)
$programFilesSevenZip = @(
    (Join-Path $env:ProgramFiles '7-Zip\7z.exe'),
    (Join-Path ${env:ProgramFiles(x86)} '7-Zip\7z.exe')
) | ForEach-Object {
    [ordered]@{ path = $_; exists = Test-Path -LiteralPath $_ -PathType Leaf }
}

$snapshot = [ordered]@{
    phase = $Phase
    captured_at = (Get-Date).ToString('o')
    user = [ordered]@{
        domain = $env:USERDOMAIN
        name = $env:USERNAME
        is_administrator = Test-IsAdministrator
    }
    operating_system = [ordered]@{
        caption = $os.Caption
        version = $os.Version
        build_number = $os.BuildNumber
        architecture = $os.OSArchitecture
        last_boot = $os.LastBootUpTime
    }
    computer = [ordered]@{
        manufacturer = $computer.Manufacturer
        model = $computer.Model
        total_physical_memory = $computer.TotalPhysicalMemory
    }
    display_dpi = Get-DisplayDpi
    displays = Get-DisplaySnapshot
    developer_mode = Get-DeveloperModeState
    git = Get-GitSnapshot $RepositoryRoot
    system_7zip_commands = $systemSevenZip
    program_files_7zip = $programFilesSevenZip
    processes = Get-ProcessSnapshot
    registry = Get-RegistrySnapshot
    install_path = [ordered]@{
        path = $InstallPath
        exists = if ($InstallPath) { Test-Path -LiteralPath $InstallPath } else { $null }
    }
    work_root = [ordered]@{
        path = $WorkRoot
        exists = Test-Path -LiteralPath $WorkRoot
    }
    temp_candidates = Get-TempSnapshot
}

if ($Phase -eq 'After') {
    Start-Sleep -Seconds 2
    $processesAfterDelay = Get-ProcessSnapshot
    $registryAfterDelay = Get-RegistrySnapshot
    $tempAfterDelay = Get-TempSnapshot

    $kaitoProcesses = @($processesAfterDelay | Where-Object { $_.name -eq 'kaito.exe' })
    $bundledSevenZipProcesses = @($processesAfterDelay | Where-Object {
        $_.name -eq '7z.exe' -and (
            ($_.executable_path -and $_.executable_path -match '(?i)\\_MEI[^\\]*\\bundled\\7z\.exe$') -or
            ($InstallPath -and $_.executable_path -and $_.executable_path.StartsWith($InstallPath, [System.StringComparison]::OrdinalIgnoreCase))
        )
    })
    $remainingRegistry = @($registryAfterDelay | Where-Object { $_.exists })
    $installPathExists = if ($InstallPath) { Test-Path -LiteralPath $InstallPath } else { $false }

    $snapshot.after_delay = [ordered]@{
        processes = $processesAfterDelay
        registry = $registryAfterDelay
        temp_candidates = $tempAfterDelay
    }
    $snapshot.cleanup_assessment = [ordered]@{
        kaito_process_count = $kaitoProcesses.Count
        bundled_7zip_process_count = $bundledSevenZipProcesses.Count
        remaining_registry_count = $remainingRegistry.Count
        install_path_exists = $installPathExists
        pass = $kaitoProcesses.Count -eq 0 -and
            $bundledSevenZipProcesses.Count -eq 0 -and
            $remainingRegistry.Count -eq 0 -and
            -not $installPathExists
    }
}

$outputPath = Join-Path $EvidenceRoot ("environment-{0}.json" -f $Phase.ToLowerInvariant())
$snapshot | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $outputPath -Encoding utf8

Write-Host "Acceptance evidence written: $outputPath"

if ($Phase -eq 'After' -and -not $snapshot.cleanup_assessment.pass) {
    Write-Error 'Acceptance cleanup check failed. Review cleanup_assessment and after_delay in the evidence JSON.'
    exit 2
}
