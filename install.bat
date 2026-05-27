@echo off
REM ============================================================
REM  Arena Unified Bridge v1.7.0 - Universal Installer
REM  Single folder, single command, cross-platform ready
REM ============================================================
setlocal enabledelayedexpansion

echo.
echo  ========================================
echo   Arena Unified Bridge v1.7.0 Installer
echo  ========================================
echo.

REM --- Configuration ---
set "BRIDGE_DIR=%~dp0"
set "BRIDGE_DIR=%BRIDGE_DIR:~0,-1%"
set "PYTHON=python"
set "PORT=8765"
set "PROFILE=owner-shell"

REM --- Check Python ---
%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ and add to PATH.
    echo         Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('%PYTHON% --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER% found

REM --- Install dependencies ---
echo.
echo [1/5] Installing Python dependencies...
%PYTHON% -m pip install aiohttp psutil --quiet 2>nul
echo       Done.

REM --- Create subdirectories ---
echo.
echo [2/5] Creating directory structure...
for %%d in (dashboard bin scripts skills tools memory missions hooks logs queue reports backups mcp docs subagents projects) do (
    if not exist "%BRIDGE_DIR%\%%d" mkdir "%BRIDGE_DIR%\%%d"
)
echo       Done.

REM --- Generate token ---
echo.
echo [3/5] Generating auth token...
if not exist "%BRIDGE_DIR%\token.txt" (
    %PYTHON% -c "import secrets; print(secrets.token_urlsafe(32))" > "%BRIDGE_DIR%\token.txt"
    echo       New token generated.
) else (
    echo       Existing token found.
)

REM --- Install as NSSM Windows Service ---
echo.
echo [4/5] Installing as Windows service...
where nssm >nul 2>&1
if errorlevel 1 (
    echo       NSSM not found. Installing via Scheduled Task instead.
    
    REM Create a startup script
    echo @echo off > "%BRIDGE_DIR%\start_bridge.bat"
    echo cd /d "%BRIDGE_DIR%" >> "%BRIDGE_DIR%\start_bridge.bat"
    echo %PYTHON% -u unified_bridge.py serve --root "%USERPROFILE%" --profile %PROFILE% --token-file token.txt --port %PORT% >> "%BRIDGE_DIR%\start_bridge.bat"
    
    REM Create scheduled task
    schtasks /create /tn "ArenaUnifiedBridge" /tr "%BRIDGE_DIR%\start_bridge.bat" /sc onstart /ru "%USERNAME%" /rl highest /f >nul 2>&1
    if errorlevel 1 (
        echo       [WARN] Could not create scheduled task. Run manually.
    ) else (
        echo       Scheduled task created.
    )
) else (
    REM NSSM available - install as proper service
    nssm install ArenaUnifiedBridge "%PYTHON%w" "-u %BRIDGE_DIR%\unified_bridge.py serve --root %USERPROFILE% --profile %PROFILE% --token-file %BRIDGE_DIR%\token.txt --port %PORT%" >nul 2>&1
    nssm set ArenaUnifiedBridge AppDirectory "%BRIDGE_DIR%" >nul 2>&1
    nssm set ArenaUnifiedBridge DisplayName "Arena Unified Bridge" >nul 2>&1
    nssm set ArenaUnifiedBridge Start SERVICE_AUTO_START >nul 2>&1
    nssm set ArenaUnifiedBridge AppStdout "%BRIDGE_DIR%\logs\bridge.log" >nul 2>&1
    nssm set ArenaUnifiedBridge AppStderr "%BRIDGE_DIR%\logs\bridge_err.log" >nul 2>&1
    echo       NSSM service installed.
)

REM --- Start the bridge ---
echo.
echo [5/5] Starting Arena Bridge...
where nssm >nul 2>&1
if not errorlevel 1 (
    nssm start ArenaUnifiedBridge >nul 2>&1
) else (
    schtasks /run /tn "ArenaUnifiedBridge" >nul 2>&1
)

timeout /t 3 /nobreak >nul

REM --- Verify ---
echo.
echo  ========================================
echo   Installation Complete!
echo  ========================================
echo.
echo   Bridge URL:    http://127.0.0.1:%PORT%
echo   Dashboard:     http://127.0.0.1:%PORT%/gui
echo   Token file:    %BRIDGE_DIR%\token.txt
echo.

REM Show token
if exist "%BRIDGE_DIR%\token.txt" (
    echo   Your auth token:
    for /f "delims=" %%t in ('type "%BRIDGE_DIR%\token.txt"') do echo   %%t
    echo.
)

echo   To stop:   nssm stop ArenaUnifiedBridge
echo   To uninstall: nssm remove ArenaUnifiedBridge confirm
echo.
pause
