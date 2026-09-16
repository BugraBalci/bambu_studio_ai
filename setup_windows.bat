@echo off
REM ============================================================================
REM  Bambu AI Studio — one-time Windows setup
REM  Creates Python venv, installs npm deps, then puts "Bambu AI Studio" on
REM  the Desktop. After this, double-click the shortcut (it runs start_app.bat).
REM ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"
title Bambu AI Studio - Windows kurulum
color 07

set "DEPS_ONLY=0"
if /I "%~1"=="--deps-only" set "DEPS_ONLY=1"

echo.
echo ============================================
echo   Bambu AI Studio — Windows kurulum
echo ============================================
echo   Klasor : %CD%
echo.

REM --- Python 3.10+ ----------------------------------------------------------
set "PY_CMD="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>nul
if not errorlevel 1 set "PY_CMD=py -3"

if not defined PY_CMD (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo [HATA] Python 3.10+ bulunamadi.
    echo.
    echo 1. https://www.python.org/downloads/ adresinden Python 3.12 kur
    echo 2. Kurulumda "Add python.exe to PATH" kutusunu isaretle
    echo 3. Bu pencereyi kapatip setup_windows.bat dosyasina tekrar cift tikla
    echo.
    pause
    exit /b 1
)

echo Python: 
%PY_CMD% --version

REM --- Node / npm ------------------------------------------------------------
where npm.cmd >nul 2>&1
if errorlevel 1 (
    echo [HATA] npm bulunamadi. Node.js 20+ gerekli.
    echo.
    echo 1. https://nodejs.org/ adresinden LTS kur
    echo 2. Kurulumdan sonra bu pencereyi kapatip setup_windows.bat'a tekrar cift tikla
    echo.
    pause
    exit /b 1
)

echo npm:
call npm.cmd --version
echo.

REM --- Backend venv + pip ----------------------------------------------------
if not exist "backend\.venv\Scripts\python.exe" (
    if exist "backend\.venv\" (
        echo Mevcut .venv Windows python.exe icermiyor, silinip yeniden olusturuluyor...
        rmdir /s /q backend\.venv
    )
    echo [1/3] Python sanal ortami olusturuluyor...
    %PY_CMD% -m venv backend\.venv
    if errorlevel 1 (
        echo [HATA] python -m venv basarisiz.
        pause
        exit /b 1
    )
) else (
    echo [1/3] backend\.venv zaten var, atlandi.
)

echo pip paketleri kuruluyor ^(ilk seferde birkac dakika surebilir^)...
"backend\.venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo [HATA] pip guncellenemedi.
    pause
    exit /b 1
)
"backend\.venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if errorlevel 1 (
    echo [HATA] pip install -r backend\requirements.txt basarisiz.
    pause
    exit /b 1
)

REM --- Frontend npm ----------------------------------------------------------
echo.
echo [2/3] frontend npm install...
pushd frontend
call npm.cmd install
if errorlevel 1 (
    popd
    echo [HATA] npm install basarisiz.
    pause
    exit /b 1
)
popd

if "%DEPS_ONLY%"=="1" (
    echo.
    echo Bagimliliklar hazir.
    exit /b 0
)

REM --- Desktop shortcut ------------------------------------------------------
echo.
echo [3/3] Masaustu kisayolu olusturuluyor...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_desktop_shortcut.ps1"
if errorlevel 1 (
    echo [HATA] Kisayol olusturulamadi. Elle dene:
    echo   powershell -ExecutionPolicy Bypass -File setup_desktop_shortcut.ps1
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Kurulum bitti
echo ============================================
echo.
echo Masaustunde "Bambu AI Studio" kisayoluna cift tikla.
echo Tarayici http://127.0.0.1:5173 adresini acar.
echo Durdurmak icin "Bambu AI Studio - Durdur" kisayolunu kullan.
echo.
choice /C EN /N /M "Simdi baslat? [E]vet / [N]hayir: "
if errorlevel 2 exit /b 0
if errorlevel 1 call "%~dp0start_app.bat"
exit /b 0
