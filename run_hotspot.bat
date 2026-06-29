@echo off
:: run_hotspot.bat — Start the RealmScape Hotspot Daemon (Windows)
:: Automatically requests Administrator privileges if not already elevated.
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: ── Check if already running as Administrator ────────────────────
net session >nul 2>&1
if %errorlevel% == 0 goto :run

:: ── Not elevated — re-launch this script elevated ────────────────
echo Requesting Administrator privileges...
set "ARGS=%*"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process -FilePath '%COMSPEC%' -ArgumentList '/k pushd ""%~dp0"" && call run_hotspot.bat !ARGS!' -Verb RunAs"
exit /b 0

:run
:: ── Running as Administrator — start the daemon ──────────────────
echo.
echo ============================================================
echo  RealmScape Hotspot Daemon
echo ============================================================
echo.

if not exist "hotspot_daemon.py" (
    echo ERROR: hotspot_daemon.py not found.
    echo        Make sure you are running this from the RealmScape directory.
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" hotspot_daemon.py %*
) else (
    python hotspot_daemon.py %*
)

echo.
echo Hotspot daemon has stopped.
pause
endlocal
