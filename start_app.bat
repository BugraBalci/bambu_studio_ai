@echo off
setlocal EnableExtensions
title Bambu AI Launcher
echo ==========================================
echo       Bambu AI Asistan Baslatiliyor...
echo ==========================================

cd /d "%~dp0"
if errorlevel 1 (
    echo [HATA] Proje kok dizinine gecilemedi.
    pause
    exit /b 1
)

if not exist "backend\.venv\Scripts\python.exe" (
    echo [HATA] Backend sanal ortami bulunamadi!
    echo Lutfen backend klasorunde 'python -m venv .venv' calistirin.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo [HATA] Frontend bagimliliklari eksik!
    echo Lutfen frontend klasorunde 'npm install' calistirin.
    pause
    exit /b 1
)

echo Backend baslatiliyor...
start "Bambu AI - Backend" powershell -NoExit -NoProfile -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%~dp0backend'; . .\.venv\Scripts\Activate.ps1; $env:PYTHONPATH = ((Get-Location).Path + '\..;' + (Get-Location).Path); python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000"

echo Frontend baslatiliyor...
start "Bambu AI - Frontend" powershell -NoExit -NoProfile -ExecutionPolicy Bypass -Command "Set-Location -LiteralPath '%~dp0frontend'; npm run dev"

echo Arayuz bekleniyor...
timeout /t 3 >nul
start http://127.0.0.1:5173
