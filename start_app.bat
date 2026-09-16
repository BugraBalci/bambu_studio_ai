@echo off
title Bambu AI Launcher
echo ==========================================
echo       Bambu AI Asistan Baslatiliyor...
echo ==========================================

if not exist "backend\.venv" (
    echo [HATA] Backend sanal ortami bulunamadi!
    echo Lutfen backend klasorunde 'python -m venv .venv' calistirin.
    pause
    exit /b
)

if not exist "frontend\node_modules" (
    echo [HATA] Frontend bagimliliklari eksik!
    echo Lutfen frontend klasorunde 'npm install' calistirin.
    pause
    exit /b
)

echo Backend baslatiliyor...
start "Bambu AI - Backend" powershell -NoExit -Command "cd backend; .\.venv\Scripts\Activate.ps1; $env:PYTHONPATH = \"$PWD\..;$PWD\"; python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"

echo Frontend baslatiliyor...
start "Bambu AI - Frontend" powershell -NoExit -Command "cd frontend; npm run dev"

echo Arayuz bekleniyor...
timeout /t 3 >nul
start http://127.0.0.1:5173