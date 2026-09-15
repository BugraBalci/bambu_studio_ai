@echo off
REM ============================================================================
REM  Bambu AI Studio — stop Windows services
REM  Terminates listeners on TCP 8000 (Uvicorn) and 5173 (Vite) and closes
REM  leftover consoles titled "Bambu AI - Backend/Frontend".
REM ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================
echo   Bambu AI Studio — stopping servers
echo ============================================
echo.

set "KILLED=0"

REM Kill process trees that own the LISTENING sockets. /T includes the
REM Uvicorn reloader child and the npm -> node tree.
for %%P in (8000 5173) do (
    for /f "tokens=5" %%A in ('netstat -ano 2^>nul ^| findstr /R /C:":%%P[ ]" ^| findstr /I "LISTENING"') do (
        if not "%%A"=="0" if not "%%A"=="4" (
            echo   Port %%P — stopping PID %%A and its child processes
            taskkill /PID %%A /T /F >nul 2>&1
            if not errorlevel 1 set "KILLED=1"
        )
    )
)

REM Close titled launcher consoles that may still be sitting at "pause".
taskkill /FI "WINDOWTITLE eq Bambu AI - Backend*"  /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Bambu AI - Frontend*" /T /F >nul 2>&1

if "!KILLED!"=="0" (
    echo No listeners found on ports 8000 or 5173.
) else (
    echo Servers stopped.
)

echo.
exit /b 0
