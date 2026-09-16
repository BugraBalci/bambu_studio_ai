#Requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "=========================================="
Write-Host "      Bambu AI Asistan Baslatiliyor..."
Write-Host "=========================================="

$backend = Join-Path $PSScriptRoot "backend"
$frontend = Join-Path $PSScriptRoot "frontend"
$venvActivate = Join-Path $backend ".venv\Scripts\Activate.ps1"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "[HATA] Backend sanal ortami bulunamadi!"
    Write-Host "Lutfen backend klasorunde 'python -m venv .venv' calistirin."
    exit 1
}

if (-not (Test-Path -LiteralPath (Join-Path $frontend "node_modules"))) {
    Write-Host "[HATA] Frontend bagimliliklari eksik!"
    Write-Host "Lutfen frontend klasorunde 'npm install' calistirin."
    exit 1
}

Write-Host "Backend baslatiliyor..."
$backendCmd = @"
Set-Location -LiteralPath '$backend'
. '$venvActivate'
`$env:PYTHONPATH = "`$PWD\..;`$PWD"
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
"@
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-Command", $backendCmd
)

Write-Host "Frontend baslatiliyor..."
$frontendCmd = @"
Set-Location -LiteralPath '$frontend'
npm run dev
"@
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-Command", $frontendCmd
)

Start-Sleep -Seconds 3
Start-Process "http://127.0.0.1:5173"
