@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Bambu AI - Stop
color 07

:: ---------------------------------------------------------------------------
:: Bambu AI Studio - clean shutdown
::  1) Force-kill whatever is LISTENING on ports 8000 (API) and 5173 (Vite)
::     including process trees so uvicorn --reload cannot respawn workers.
::  2) Close leftover consoles titled "Bambu AI - Backend" / "Bambu AI - Frontend"
:: ---------------------------------------------------------------------------

cd /d "%~dp0"

echo.
echo ============================================
echo   Stopping Bambu AI Studio
echo ============================================
echo.

call :kill_port 8000
call :kill_port 5173

echo.
echo Closing leftover Bambu AI console windows...
:: /T kills the console plus child python/node processes.
:: Wildcard covers titles that cmd.exe or a child process may suffix.
taskkill /F /T /FI "WINDOWTITLE eq Bambu AI - Backend*"  >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq Bambu AI - Frontend*" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq Bambu AI - Backend"   >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq Bambu AI - Frontend"  >nul 2>&1

echo.
echo Done.
timeout /t 3 /nobreak >nul
exit /b 0

:: Kill every LISTENING PID bound to the given TCP port (IPv4 and IPv6).
:kill_port
set "PORT=%~1"
set "KILLED=0"
echo Scanning port %PORT% ...

for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr "LISTENING" ^| findstr ":%PORT%"') do (
    call :kill_pid %%P
)

if "!KILLED!"=="0" (
    echo   No LISTENING process on port %PORT%.
)
goto :eof

:: Resolve parent first (uvicorn reloader), then taskkill /F /PID /T.
:kill_pid
set "PID=%~1"
if "%PID%"=="" goto :eof
if "%PID%"=="0" goto :eof

set "PPID="
for /f "tokens=2 delims==" %%Q in ('wmic process where "ProcessId=%PID%" get ParentProcessId /value 2^>nul') do (
    for /f "delims=" %%R in ("%%Q") do set "PPID=%%R"
)

echo   taskkill /F /PID %PID% /T  ^(port %PORT%^)
taskkill /F /PID %PID% /T >nul 2>&1
if not errorlevel 1 (
    set "KILLED=1"
    echo     stopped PID %PID%
) else (
    echo     PID %PID% already gone or access denied
)

if not "!PPID!"=="" if not "!PPID!"=="0" (
    taskkill /F /PID !PPID! /T >nul 2>&1
    if not errorlevel 1 echo     stopped parent PID !PPID!
)
goto :eof
