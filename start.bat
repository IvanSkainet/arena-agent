@echo off
REM ============================================================
REM  Arena Unified Bridge — Start Script (Windows)
REM ============================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"
set "BRIDGE_DIR=%~dp0"
set "BRIDGE_DIR=%BRIDGE_DIR:~0,-1%"
set "PORT=8765"
set "TOKEN_FILE=token.txt"

REM --- Find Python ---
set "PYTHON="
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not defined PYTHON (
    if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
)
if not defined PYTHON (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PYTHON (
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)
if not defined PYTHON (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON=python"
)
if not defined PYTHON (
    where py >nul 2>&1
    if not errorlevel 1 set "PYTHON=py -3"
)
if not defined PYTHON (
    echo [ERROR] Python not found in PATH or standard install locations.
    echo         Please install Python 3.10+ from python.org and check "Add Python to PATH".
    pause
    exit /b 1
)

REM --- Check if already running ---
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr /I "LISTENING"') do (
    echo [WARN] Bridge is already listening on port %PORT% (PID: %%P).
    echo        To restart cleanly, run stop.bat first.
    echo.
)

REM --- Generate token if not exists ---
if not exist "%TOKEN_FILE%" (
    "%PYTHON%" -c "import secrets; open('token.txt', 'w').write(secrets.token_urlsafe(32))" 2>nul
)

set "TOKEN="
if exist "%TOKEN_FILE%" (
    set /p "TOKEN="<"%TOKEN_FILE%"
)

echo.
echo ============================================================
echo   Arena Unified Bridge
echo ============================================================
echo   Local API:  http://127.0.0.1:%PORT%
if defined TOKEN (
    echo   Token:      !TOKEN!
)
echo   Dashboard:  http://127.0.0.1:%PORT%/gui
echo ============================================================
echo.
echo   Press Ctrl+C to stop the bridge, or run stop.bat.
echo.

"%PYTHON%" -u unified_bridge.py serve --root "%USERPROFILE%" --profile owner-shell --token-file "%TOKEN_FILE%" --port %PORT%
pause
