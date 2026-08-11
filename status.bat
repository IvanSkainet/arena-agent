@echo off
REM ============================================================
REM  Arena Unified Bridge — Status ^& Reachability Diagnostic
REM ============================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"

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

if defined PYTHON (
    "%PYTHON%" scripts\check_bridge.py %*
) else (
    curl -s http://127.0.0.1:8765/health 2>nul
    if errorlevel 1 (
        echo  [DOWN] Bridge is not responding
    ) else (
        echo  [UP] Bridge is running
    )
)

echo.
pause
