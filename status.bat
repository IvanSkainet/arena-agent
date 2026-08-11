@echo off
REM ============================================================
REM  Arena Unified Bridge — Проверка статуса и доступности
REM ============================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"
set "BRIDGE_DIR=%~dp0"
if "%BRIDGE_DIR:~-1%"=="\" set "BRIDGE_DIR=%BRIDGE_DIR:~0,-1%"

REM --- Поиск Python ---
set "PYTHON="
if exist "!BRIDGE_DIR!\.venv\Scripts\python.exe" set "PYTHON=!BRIDGE_DIR!\.venv\Scripts\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PYTHON (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON=python"
)
if not defined PYTHON (
    where py >nul 2>&1
    if not errorlevel 1 set "PYTHON=py -3"
)
if not defined PYTHON (
    where python3 >nul 2>&1
    if not errorlevel 1 set "PYTHON=python3"
)

if defined PYTHON (
    if exist "!BRIDGE_DIR!\scripts\check_bridge.py" (
        "!PYTHON!" "!BRIDGE_DIR!\scripts\check_bridge.py" %*
        goto :end
    )
)

echo.
echo  ============================================================
echo    Arena Bridge Status
echo  ============================================================
curl -s http://127.0.0.1:8765/health 2>nul
if errorlevel 1 (
    echo  [DOWN] Мост не запущен или не отвечает на порту 8765.
) else (
    echo.
    echo  [UP] Мост успешно работает на http://127.0.0.1:8765
)
echo.

:end
pause
