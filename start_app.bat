@echo off
setlocal EnableExtensions
title Bambu AI - Launcher
color 07

:: ---------------------------------------------------------------------------
:: Bambu AI Studio - one-click launcher
:: Spawns backend (FastAPI/uvicorn) and frontend (Vite) in dedicated consoles,
:: then opens the UI in the default browser once http://127.0.0.1:5173 is up.
:: ---------------------------------------------------------------------------

:: Always run from this script's directory so relative paths are stable,
:: even when launched from a desktop shortcut or a different CWD.
cd /d "%~dp0"
set "ROOT=%CD%"

echo.
echo ============================================
echo   Bambu AI Studio
echo ============================================
echo   Repo: %ROOT%
echo.

:: --- Pre-flight: Python virtual environment --------------------------------
if not exist "%ROOT%\backend\.venv\" (
    call :print_red "ERROR: Python virtual environment not found at backend\.venv"
    echo.
    echo Create it from the repo root with:
    echo   cd backend
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "%ROOT%\backend\.venv\Scripts\python.exe" (
    call :print_red "ERROR: backend\.venv exists but Scripts\python.exe is missing."
    echo.
    echo Recreate it with:
    echo   cd backend
    echo   python -m venv .venv
    echo.
    pause
    exit /b 1
)

:: --- Pre-flight: frontend dependencies -------------------------------------
if not exist "%ROOT%\frontend\node_modules\" (
    call :print_red "ERROR: frontend\node_modules not found."
    echo.
    echo Install frontend dependencies with:
    echo   cd frontend
    echo   npm install
    echo.
    pause
    exit /b 1
)

:: PYTHONPATH must include the repo root and backend\ so `app.main:app` resolves.
:: Child consoles inherit this environment from the launcher process.
set "PYTHONPATH=%ROOT%;%ROOT%\backend"

echo Starting backend on http://127.0.0.1:8000 ...
:: Dedicated titled console. /D sets CWD to backend\ so we can call the venv
:: interpreter with a space-free relative path. cmd /k keeps errors visible.
start "Bambu AI - Backend" /D "%ROOT%\backend" cmd.exe /k ".venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"

echo Starting frontend on http://127.0.0.1:5173 ...
:: Launch via cmd.exe (not PowerShell) so Windows uses npm.cmd instead of
:: npm.ps1, which is frequently blocked by ExecutionPolicy / PSSecurityException.
start "Bambu AI - Frontend" /D "%ROOT%" cmd.exe /k "cd frontend && npm run dev"

echo.
echo Waiting for the Vite dev server (up to 20 seconds^) ...

:: Lightweight HTTP poll: 40 x 500ms ~= 20s, then open the default browser.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ready=$false; foreach($n in 1..40){ if($ready){ break }; try { Invoke-WebRequest -Uri 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 1 | Out-Null; $ready=$true } catch { Start-Sleep -Milliseconds 500 } }; if($ready){ Start-Process 'http://127.0.0.1:5173'; exit 0 }; Write-Host 'Frontend did not become ready within 20 seconds.' -ForegroundColor Yellow; exit 1"

if errorlevel 1 (
    echo.
    echo You can open the UI manually: http://127.0.0.1:5173
    echo Backend API:                 http://127.0.0.1:8000
    echo.
    pause
    exit /b 1
)

echo.
echo Backend:  http://127.0.0.1:8000
echo Frontend: http://127.0.0.1:5173
echo.
echo Close this window anytime. Use stop_app.bat to shut services down.
timeout /t 4 /nobreak >nul
exit /b 0

:: --- helpers ---------------------------------------------------------------
:print_red
powershell.exe -NoProfile -Command "Write-Host '%~1' -ForegroundColor Red"
goto :eof
