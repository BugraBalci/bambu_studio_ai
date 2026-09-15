#Requires -Version 5.1
<#
.SYNOPSIS
    Creates a Desktop shortcut that launches Bambu AI Studio via start_app.bat.

.DESCRIPTION
    Resolves this user's Desktop (including OneDrive-redirected Desktops),
    points a "Bambu AI Studio.lnk" shortcut at start_app.bat in the repo root,
    and sets WorkingDirectory so relative backend/frontend paths resolve.

    Run from the project root (ExecutionPolicy Bypass is enough; no admin):

        powershell -ExecutionPolicy Bypass -File .\setup_desktop_shortcut.ps1
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-UserDesktop {
    $desktop = [Environment]::GetFolderPath('Desktop')
    if (-not [string]::IsNullOrWhiteSpace($desktop) -and (Test-Path -LiteralPath $desktop)) {
        return $desktop
    }

    $fallback = Join-Path $env:USERPROFILE 'Desktop'
    if (Test-Path -LiteralPath $fallback) {
        return $fallback
    }

    throw "Could not locate the current user's Desktop folder."
}

function Get-ShortcutIcon([string]$Root) {
    $pythonExe = Join-Path $Root 'backend\.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $pythonExe) {
        return "$pythonExe,0"
    }

    $imageres = Join-Path $env:SystemRoot 'System32\imageres.dll'
    if (Test-Path -LiteralPath $imageres) {
        # 109 = printer glyph on Windows 10/11 — fits a print-studio launcher.
        return "$imageres,109"
    }

    $shell32 = Join-Path $env:SystemRoot 'System32\shell32.dll'
    return "$shell32,13"
}

try {
    $root = $PSScriptRoot
    if ([string]::IsNullOrWhiteSpace($root)) {
        $root = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    $root = [System.IO.Path]::GetFullPath($root)

    $launcher = Join-Path $root 'start_app.bat'
    if (-not (Test-Path -LiteralPath $launcher)) {
        throw "start_app.bat was not found next to this script:`n  $launcher"
    }

    $desktop = Get-UserDesktop
    $linkPath = Join-Path $desktop 'Bambu AI Studio.lnk'

    Write-Host "Project root : $root"
    Write-Host "Launcher     : $launcher"
    Write-Host "Desktop      : $desktop"
    Write-Host "Shortcut     : $linkPath"

    $wsh = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $wsh.CreateShortcut($linkPath)
        $shortcut.TargetPath = $launcher
        $shortcut.WorkingDirectory = $root
        $shortcut.WindowStyle = 1
        $shortcut.Description = 'Launch Bambu AI Studio (FastAPI + Vite)'
        $shortcut.IconLocation = Get-ShortcutIcon -Root $root
        $shortcut.Save()
    }
    finally {
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($wsh)
    }

    if (-not (Test-Path -LiteralPath $linkPath)) {
        throw "Shortcut was not created at $linkPath"
    }

    Write-Host ""
    Write-Host "Created Desktop shortcut: Bambu AI Studio"
    Write-Host "Double-click it after backend\.venv and frontend\node_modules exist."
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
