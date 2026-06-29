@echo off
:: install.bat — RealmScape installer
:: Requires Python 3.10-3.12. Python 3.13+ is not compatible with skia-python
:: (used by the optional DungeonGen integration).
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  RealmScape — Windows Installer
echo ============================================================
echo.

:: ── Locate Python 3.10-3.12 via Windows Python Launcher ───────
::
:: Python 3.13 is intentionally excluded for DungeonGen compatibility.
:: The Python Launcher (py) is the most reliable way to pick a specific
:: version on Windows when multiple versions are installed.

set PYTHON_CMD=

:: 1. Try Python Launcher (py -3.12, -3.11, -3.10)
where py >nul 2>&1
if not errorlevel 1 (
    for %%V in (3.12 3.11 3.10) do (
        if "!PYTHON_CMD!"=="" (
            py -%%V --version >nul 2>&1
            if not errorlevel 1 set PYTHON_CMD=py -%%V
        )
    )
)

:: 2. Fall back to direct version-suffixed commands
if "!PYTHON_CMD!"=="" (
    for %%P in (python3.12 python3.11 python3.10) do (
        if "!PYTHON_CMD!"=="" (
            where %%P >nul 2>&1
            if not errorlevel 1 set PYTHON_CMD=%%P
        )
    )
)

:: 3. Last resort: python3/python — only accept 3.10-3.12
if "!PYTHON_CMD!"=="" (
    for %%P in (python3 python) do (
        if "!PYTHON_CMD!"=="" (
            where %%P >nul 2>&1
            if not errorlevel 1 (
                for /f "delims=" %%E in ('%%P -c "import sys; mi=sys.version_info.minor; maj=sys.version_info.major; print(sys.executable if maj==3 and 10<=mi<=12 else \"\")" 2^>nul') do (
                    if not "%%E"=="" set PYTHON_CMD=%%P
                )
            )
        )
    )
)

if "!PYTHON_CMD!"=="" (
    echo ERROR: No compatible Python found ^(3.10, 3.11, or 3.12 required^).
    echo.
    echo  Python 3.13 is installed but is not compatible with the DungeonGen
    echo  integration library ^(skia-python has no 3.13 wheels^).
    echo  Install Python 3.12 from https://www.python.org/downloads/
    echo  and check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

for /f "delims=" %%V in ('!PYTHON_CMD! -c "import sys; print(f\"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\")"') do set PYTHON_VER=%%V
echo Using Python %PYTHON_VER%  ^(!PYTHON_CMD!^)
echo.

:: ── Create virtual environment ─────────────────────────────────
if exist ".venv\Scripts\python.exe" (
    echo Virtual environment already exists, skipping creation.
    echo.
) else (
    echo Creating virtual environment...
    !PYTHON_CMD! -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo Done.
    echo.
)

:: ── Install dependencies ───────────────────────────────────────
echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Installation complete!
echo.
echo  To start RealmScape, double-click run.bat or run:
echo    .venv\Scripts\python.exe main.py
echo ============================================================
echo.
pause
endlocal
