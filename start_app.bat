@echo off
REM ============================================================================
REM  Bambu AI Studio — one-click Windows launcher
REM  Spawns titled Backend (Uvicorn) and Frontend (Vite) consoles, then opens
REM  the UI in the default browser. Double-click this file or use the Desktop
REM  shortcut created by setup_desktop_shortcut.ps1.
REM ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

REM Self-reinvoke: child consoles land here so paths with spaces stay quoted.
if /I "%~1"=="--backend"  goto :start_backend
if /I "%~1"=="--frontend" goto :start_frontend

set "ROOT=%CD%"
set "VENV_DIR=%ROOT%\backend\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "NODE_MODULES=%ROOT%\frontend\node_modules"
set "API_PORT=8000"
set "UI_PORT=5173"

echo.
echo ============================================
echo   Bambu AI Studio — Windows launcher
echo ============================================
echo   Project : %ROOT%
echo   API     : http://127.0.0.1:%API_PORT%
echo   UI      : http://127.0.0.1:%UI_PORT%
echo.

REM --- Prerequisites ----------------------------------------------------------

if not exist "%VENV_DIR%\" (
    echo [ERROR] backend\.venv was not found.
    echo.
    echo Create and populate the virtual environment first:
    echo   cd backend
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "%VENV_PY%" (
    echo [ERROR] backend\.venv exists but Scripts\python.exe is missing.
    echo This usually means the venv was created on Linux/macOS, not Windows.
    echo Recreate it on this machine:
    echo   cd backend
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "%NODE_MODULES%\" (
    echo [ERROR] frontend\node_modules was not found.
    echo.
    echo Install frontend dependencies first:
    echo   cd frontend
    echo   npm install
    echo.
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm was not found on PATH.
    echo Install Node.js 20+ from https://nodejs.org/ and reopen this launcher.
    echo.
    pause
    exit /b 1
)

REM --- Spawn service windows -------------------------------------------------

echo Starting backend  ^(Uvicorn on port %API_PORT%^)...
start "Bambu AI - Backend" cmd /k call "%~f0" --backend

echo Starting frontend ^(Vite on port %UI_PORT%^)...
start "Bambu AI - Frontend" cmd /k call "%~f0" --frontend

echo.
echo Waiting for the UI to accept connections on port %UI_PORT%...

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$d=(Get-Date).AddSeconds(25); $r=$false; while((Get-Date) -lt $d){ try { $c=New-Object Net.Sockets.TcpClient; $a=$c.BeginConnect('127.0.0.1',5173,$null,$null); if($a.AsyncWaitHandle.WaitOne(300,$false) -and $c.Connected){ $r=$true }; $c.Close() } catch {} ; if($r){ break }; Start-Sleep -Milliseconds 400 }; if($r){ exit 0 }; exit 1"

if errorlevel 1 (
    echo.
    echo [WARN] Timed out waiting for http://127.0.0.1:%UI_PORT%
    echo The browser will still open. If the page fails, wait a few seconds
    echo and refresh, or check the "Bambu AI - Frontend" window for errors.
) else (
    echo Frontend is ready.
)

echo Opening http://127.0.0.1:%UI_PORT% in your default browser...
start "" "http://127.0.0.1:%UI_PORT%"

echo.
echo Two console windows will stay open while the app runs.
echo Close those windows, or run stop_app.bat, to shut the servers down.
echo.
timeout /t 3 /nobreak >nul
exit /b 0

REM --- Child: FastAPI / Uvicorn ----------------------------------------------
:start_backend
title Bambu AI - Backend
cd /d "%~dp0backend"
if errorlevel 1 (
    echo [ERROR] Could not change directory to backend.
    pause
    exit /b 1
)

REM Trailing backslash on %~dp0 is required; PYTHONPATH uses ; on Windows.
set "PYTHONPATH=%~dp0;%~dp0backend"

echo.
echo [Backend] PYTHONPATH=%PYTHONPATH%
echo [Backend] Interpreter: .venv\Scripts\python.exe
echo [Backend] http://127.0.0.1:8000
echo.

".venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
set "EC=%ERRORLEVEL%"
echo.
echo Backend process exited with code %EC%.
pause
exit /b %EC%

REM --- Child: Vite / React ---------------------------------------------------
:start_frontend
title Bambu AI - Frontend
cd /d "%~dp0frontend"
if errorlevel 1 (
    echo [ERROR] Could not change directory to frontend.
    pause
    exit /b 1
)

echo.
echo [Frontend] Working directory: %CD%
echo [Frontend] http://127.0.0.1:5173
echo.

call npm run dev
set "EC=%ERRORLEVEL%"
echo.
echo Frontend process exited with code %EC%.
pause
exit /b %EC%
