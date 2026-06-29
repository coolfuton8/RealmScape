@echo off
:: install_hotspot.bat — RealmScape Hotspot Daemon installer (Windows)
:: Verifies Python and WiFi adapter capability.
:: The daemon uses only Python stdlib — no pip packages are required.
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  RealmScape Hotspot Daemon — Windows Setup Check
echo ============================================================
echo.

:: ── Check that the main app is installed ────────────────────────
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Main RealmScape app is not installed.
    echo        Run install.bat first, then re-run this script.
    echo.
    pause
    exit /b 1
)
echo [OK] Main app virtual environment found.

:: ── Verify Python works in the venv ─────────────────────────────
".venv\Scripts\python.exe" -c "import sys; sys.exit(0)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Virtual environment Python is not working.
    echo        Re-run install.bat to repair it.
    echo.
    pause
    exit /b 1
)
for /f "delims=" %%V in ('".venv\Scripts\python.exe" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"') do set PY_VER=%%V
echo [OK] Python %PY_VER% in virtual environment.

:: ── Check hotspot_daemon.py is present ──────────────────────────
if not exist "hotspot_daemon.py" (
    echo ERROR: hotspot_daemon.py not found in this directory.
    echo.
    pause
    exit /b 1
)
echo [OK] hotspot_daemon.py found.

:: ── Verify netsh wlan is available ──────────────────────────────
where netsh >nul 2>&1
if errorlevel 1 (
    echo ERROR: netsh not found. This should not happen on Windows.
    pause
    exit /b 1
)
echo [OK] netsh is available.

:: ── Check WiFi adapter hosted-network support ────────────────────
echo.
echo Checking WiFi adapter capability...
netsh wlan show drivers 2>nul | findstr /i "Hosted network supported" >nul 2>&1
if errorlevel 1 (
    echo [WARN] Could not determine hosted network support.
    echo        No WiFi adapter may be present, or the WLAN service is stopped.
    echo        The daemon will report a clearer error when run.
) else (
    netsh wlan show drivers | findstr /i "Yes" >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Your WiFi adapter does NOT support hosted-network mode.
        echo        The daemon will not be able to create a hotspot with this adapter.
        echo        Try a USB WiFi adapter that supports AP mode.
    ) else (
        echo [OK] WiFi adapter supports hosted-network mode.
    )
)

echo.
echo ============================================================
echo  Setup check complete!
echo.
echo  To start the hotspot daemon, run:
echo    run_hotspot.bat
echo.
echo  The script will request Administrator privileges automatically.
echo  A new random WiFi password is generated each time it starts.
echo.
echo  Optional arguments ^(pass via command line^):
echo    --ssid NAME    Change the network name  ^(default: RealmScape-DM^)
echo    --port PORT    Change the app port      ^(default: 5000^)
echo ============================================================
echo.
pause
endlocal
