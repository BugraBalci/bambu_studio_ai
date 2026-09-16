#Requires -Version 5.1
<#
.SYNOPSIS
    Creates a "Bambu AI Studio" desktop shortcut that launches start_app.bat.

.DESCRIPTION
    Uses the WScript.Shell COM object to write Bambu AI Studio.lnk onto every
    detected Desktop folder (local profile Desktop and OneDrive-redirected
    Desktop paths). Target and working directory are absolute paths to this
    repository so the shortcut works regardless of the current directory.

    Icon: backend\.venv\Scripts\python.exe when present, otherwise a standard
    Windows system icon.

.NOTES
    If execution policy blocks this script, run:
      powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_desktop_shortcut.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-RepoRoot {
    if ($PSScriptRoot) {
        return [System.IO.Path]::GetFullPath($PSScriptRoot)
    }
    if ($MyInvocation.MyCommand.Path) {
        return [System.IO.Path]::GetFullPath(
            (Split-Path -Parent $MyInvocation.MyCommand.Path)
        )
    }
    return [System.IO.Path]::GetFullPath((Get-Location).Path)
}

function Get-DesktopDirectories {
    <#
        Collect unique, existing Desktop folders covering:
          - [Environment]::GetFolderPath('Desktop')  (honors Known Folder + OneDrive redirection)
          - Explorer User Shell Folders registry
          - %USERPROFILE%\Desktop
          - OneDrive / OneDriveConsumer / OneDriveCommercial\Desktop
    #>
    $candidates = New-Object System.Collections.Generic.List[string]

    $special = [Environment]::GetFolderPath([Environment+SpecialFolder]::Desktop)
    if ($special) { [void]$candidates.Add($special) }

    $specialPhysical = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
    if ($specialPhysical) { [void]$candidates.Add($specialPhysical) }

    $regPaths = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'
    )
    foreach ($regPath in $regPaths) {
        if (-not (Test-Path $regPath)) { continue }
        try {
            $props = Get-ItemProperty -Path $regPath -ErrorAction Stop
        } catch {
            continue
        }
        foreach ($name in @('Desktop', 'DesktopDirectory')) {
            $prop = $props.PSObject.Properties[$name]
            if (-not $prop -or -not $prop.Value) { continue }
            $expanded = [Environment]::ExpandEnvironmentVariables([string]$prop.Value)
            [void]$candidates.Add($expanded)
        }
    }

    if ($env:USERPROFILE) {
        [void]$candidates.Add((Join-Path $env:USERPROFILE 'Desktop'))
    }

    foreach ($envName in @('OneDrive', 'OneDriveConsumer', 'OneDriveCommercial')) {
        $od = [Environment]::GetEnvironmentVariable($envName, 'Process')
        if (-not $od) {
            $od = [Environment]::GetEnvironmentVariable($envName, 'User')
        }
        if ($od) {
            [void]$candidates.Add((Join-Path $od 'Desktop'))
        }
    }

    # Common OneDrive folder names when env vars are absent
    if ($env:USERPROFILE) {
        foreach ($leaf in @('OneDrive', 'OneDrive - Personal')) {
            $odRoot = Join-Path $env:USERPROFILE $leaf
            if (Test-Path -LiteralPath $odRoot -PathType Container) {
                [void]$candidates.Add((Join-Path $odRoot 'Desktop'))
            }
        }

        Get-ChildItem -Path $env:USERPROFILE -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like 'OneDrive*' } |
            ForEach-Object {
                [void]$candidates.Add((Join-Path $_.FullName 'Desktop'))
            }
    }

    $unique = New-Object System.Collections.Generic.List[string]
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($path in $candidates) {
        if (-not $path) { continue }
        try {
            $full = [System.IO.Path]::GetFullPath($path)
        } catch {
            continue
        }
        if (-not (Test-Path -LiteralPath $full -PathType Container)) { continue }
        if ($seen.Add($full)) {
            [void]$unique.Add($full)
        }
    }

    return $unique
}

function Get-ShortcutIconLocation {
    param(
        [Parameter(Mandatory = $true)]
        [string] $RepoRoot
    )

    $pythonExe = Join-Path $RepoRoot 'backend\.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $pythonExe -PathType Leaf) {
        return "$pythonExe,0"
    }

    $imageres = Join-Path $env:SystemRoot 'System32\imageres.dll'
    if (Test-Path -LiteralPath $imageres) {
        # 109 = application / window glyph in imageres.dll
        return "$imageres,109"
    }

    $shell32 = Join-Path $env:SystemRoot 'System32\shell32.dll'
    if (Test-Path -LiteralPath $shell32) {
        return "$shell32,25"
    }

    $cmd = Join-Path $env:SystemRoot 'System32\cmd.exe'
    return "$cmd,0"
}

$repoRoot = Get-RepoRoot
$startBat = Join-Path $repoRoot 'start_app.bat'

if (-not (Test-Path -LiteralPath $startBat -PathType Leaf)) {
    Write-Host "ERROR: start_app.bat not found at:" -ForegroundColor Red
    Write-Host "  $startBat"
    Write-Host "Run this script from the repository root."
    exit 1
}

$desktops = @(Get-DesktopDirectories)
if ($desktops.Count -eq 0) {
    Write-Host "ERROR: Could not locate a Desktop folder (local or OneDrive)." -ForegroundColor Red
    exit 1
}

$icon = Get-ShortcutIconLocation -RepoRoot $repoRoot
$wsh = $null
$created = New-Object System.Collections.Generic.List[string]

try {
    $wsh = New-Object -ComObject WScript.Shell
    foreach ($desktop in $desktops) {
        $lnkPath = Join-Path $desktop 'Bambu AI Studio.lnk'
        $shortcut = $wsh.CreateShortcut($lnkPath)
        $shortcut.TargetPath       = $startBat
        $shortcut.WorkingDirectory = $repoRoot
        $shortcut.WindowStyle      = 1
        $shortcut.Description      = 'Launch Bambu AI Studio (FastAPI backend + Vite frontend)'
        $shortcut.IconLocation     = $icon
        $shortcut.Save()
        [void]$created.Add($lnkPath)
        Write-Host "Created: $lnkPath" -ForegroundColor Green
    }
}
finally {
    if ($wsh) {
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($wsh)
    }
}

Write-Host ""
Write-Host ("Created {0} shortcut(s)." -f $created.Count)
Write-Host "Shortcut name : Bambu AI Studio.lnk"
Write-Host "Target        : $startBat"
Write-Host "Working dir   : $repoRoot"
Write-Host "Icon          : $icon"
Write-Host ""
Write-Host "Double-click the desktop shortcut to start the app."
