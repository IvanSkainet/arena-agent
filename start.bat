@echo off
REM ============================================================
REM  Arena Unified Bridge — One-Click Start Script (Windows)
REM ============================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"
set "BRIDGE_DIR=%~dp0"
if "%BRIDGE_DIR:~-1%"=="\" set "BRIDGE_DIR=%BRIDGE_DIR:~0,-1%"
set "PORT=8765"
set "TOKEN_FILE=!BRIDGE_DIR!\token.txt"

echo.
echo  ============================================================
echo    Arena Unified Bridge — Запуск
echo  ============================================================
echo.

REM --- 1. Поиск Python ---
set "PYTHON="
if exist "!BRIDGE_DIR!\.venv\Scripts\python.exe" set "PYTHON=!BRIDGE_DIR!\.venv\Scripts\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python314\python.exe" set "PYTHON=%ProgramFiles%\Python314\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python313\python.exe" set "PYTHON=%ProgramFiles%\Python313\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python312\python.exe" set "PYTHON=%ProgramFiles%\Python312\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python311\python.exe" set "PYTHON=%ProgramFiles%\Python311\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python310\python.exe" set "PYTHON=%ProgramFiles%\Python310\python.exe"
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

if not defined PYTHON (
    echo  [ОШИБКА] Python 3.10+ не найден на компьютере^^!
    echo.
    echo  Установите Python с официального сайта:
    echo  https://www.python.org/downloads/
    echo  ОБЯЗАТЕЛЬНО отметьте галочку: "Add python.exe to PATH"
    echo.
    pause
    exit /b 1
)

REM --- 2. Автоматическая проверка и установка зависимостей ---
"!PYTHON!" -c "import aiohttp, psutil, websockets" >nul 2>&1
if errorlevel 1 (
    echo  [INFO] Установка необходимых библиотек (aiohttp, psutil, websockets)...
    if exist "!BRIDGE_DIR!\requirements.txt" (
        "!PYTHON!" -m pip install -q -r "!BRIDGE_DIR!\requirements.txt" 2>nul
    ) else (
        "!PYTHON!" -m pip install -q aiohttp psutil websockets 2>nul
    )
    "!PYTHON!" -c "import aiohttp, psutil, websockets" >nul 2>&1
    if errorlevel 1 (
        echo  [INFO] Пробуем с ключом --user...
        if exist "!BRIDGE_DIR!\requirements.txt" (
            "!PYTHON!" -m pip install --user -q -r "!BRIDGE_DIR!\requirements.txt" 2>nul
        ) else (
            "!PYTHON!" -m pip install --user -q aiohttp psutil websockets 2>nul
        )
    )
)

REM --- 3. Проверка и генерация токена ---
if not exist "!TOKEN_FILE!" (
    "!PYTHON!" -c "import secrets; open('token.txt', 'w').write(secrets.token_urlsafe(32))" 2>nul
)

set "TOKEN="
if exist "!TOKEN_FILE!" (
    set /p "TOKEN="<"!TOKEN_FILE!"
)

if defined TOKEN (
    <nul set /p="!TOKEN!" | clip 2>nul
)

REM --- 4. Проверка занятости порта ---
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr /I "LISTENING"') do (
    echo  [ВНИМАНИЕ] Порт %PORT% уже занят процессом PID: %%P.
    echo  Завершаем старый процесс моста перед запуском...
    taskkill /F /PID %%P >nul 2>&1
    timeout /t 1 /nobreak >nul
)

echo  ============================================================
echo    МОСТ ГОТОВ К РАБОТЕ!
echo  ============================================================
echo    Локальный адрес:  http://127.0.0.1:%PORT%
if defined TOKEN (
    echo    Токен доступа:    !TOKEN!
    echo    (Токен скопирован в буфер обмена!)
)
echo    Дашборд моста:    http://127.0.0.1:%PORT%/gui
echo  ============================================================
echo.
echo    Для проверки удалённой доступности запустите: status.bat
echo    Для остановки закройте это окно или запустите: stop.bat
echo.
echo  ============================================================
echo.

"!PYTHON!" -u unified_bridge.py serve --root "%USERPROFILE%" --profile owner-shell --token-file "!TOKEN_FILE!" --port %PORT%
pause
