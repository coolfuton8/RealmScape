@echo off
:: clean_for_deploy.bat — Remove personal data and dev artifacts before sharing RealmScape
:: Keeps: all source code, static assets, default campaign (example), manual, scripts
:: Removes: secrets, personal campaigns, audio cache, bytecode, backup files
cd /d "%~dp0"

echo ============================================================
echo  RealmScape — Deployment Cleaner
echo ============================================================
echo.
echo The following will be PERMANENTLY deleted from this folder:
echo.
echo   [Secrets]
echo     campaigns\.web_secret
echo     campaigns\.app_lock
echo     spotify_auth.json
echo.
echo   [Personal / runtime state]
echo     campaigns\active.json
echo     characters.db
echo     .install_id  (anonymous telemetry id)
echo     DEMO_MODE  (demo/kiosk mode toggle)
echo     All campaign folders except "default"
echo.
echo   [Cache and generated files]
echo     cache\audio\  (downloaded MP3s)
echo     __pycache__\  (Python bytecode)
echo.
echo   [Dev artifacts]
echo     *.bak
echo     *.org
echo.
echo   The "default" campaign folder will NOT be touched.
echo.
set /p CONFIRM=Type YES to proceed:
if /i not "%CONFIRM%"=="YES" (
    echo Cancelled.
    exit /b 0
)
echo.

:: ── Secrets ──────────────────────────────────────────────────
call :remove_file "campaigns\.web_secret"
call :remove_file "campaigns\.app_lock"
call :remove_file "spotify_auth.json"

:: ── Runtime state ────────────────────────────────────────────
call :remove_file "campaigns\active.json"
call :remove_file "characters.db"
call :remove_file ".install_id"
call :remove_file "DEMO_MODE"

:: ── Non-default campaign folders ─────────────────────────────
for /d %%C in ("campaigns\*") do (
    if /i not "%%~nxC"=="default" (
        echo Removing campaign: %%~nxC
        rd /s /q "%%C"
    )
)

:: ── Audio cache ───────────────────────────────────────────────
call :remove_dir "cache\audio"

:: ── Python bytecode ──────────────────────────────────────────
call :remove_dir "__pycache__"
for /d /r %%D in (__pycache__) do (
    if exist "%%D" rd /s /q "%%D"
)

:: ── Dev artifacts ────────────────────────────────────────────
for %%F in (*.bak *.org) do (
    echo Removing: %%F
    del /f /q "%%F"
)

echo.
echo ============================================================
echo  Done. Repo is clean for deployment.
echo ============================================================
exit /b 0

:: ── Helpers ──────────────────────────────────────────────────
:remove_file
if exist "%~1" (
    del /f /q "%~1"
    echo Removed: %~1
) else (
    echo Already gone: %~1
)
exit /b 0

:remove_dir
if exist "%~1\" (
    rd /s /q "%~1"
    echo Removed: %~1\
) else (
    echo Already gone: %~1\
)
exit /b 0
