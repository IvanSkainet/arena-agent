@echo off
REM ============================================================
REM  Arena Unified Bridge v1.8.1 - Universal Windows Installer
REM  One folder, one command. Everything stays in this directory.
REM ============================================================
setlocal enabledelayedexpansion

echo.
echo  ========================================
echo   Arena Unified Bridge v1.8.1 Installer
echo  ========================================
echo.

REM --- All paths are inside THIS directory ---
set "BRIDGE_DIR=%~dp0"
set "BRIDGE_DIR=%BRIDGE_DIR:~0,-1%"
set "PYTHON=python"
set "PORT=8765"
set "PROFILE=owner-shell"
set "TOKEN_FILE=%BRIDGE_DIR%\token.txt"

REM --- Check Python ---
%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ and add to PATH.
    echo         Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('%PYTHON% --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER% found

REM --- Install dependencies ---
echo.
echo [1/4] Installing Python dependencies...
%PYTHON% -m pip install aiohttp psutil --quiet 2>nul
echo       Done.

REM --- Create subdirectories (all inside BRIDGE_DIR) ---
echo.
echo [2/4] Creating directory structure...
for %%d in (memory missions hooks logs queue\inbox queue\running queue\done queue\failed reports backups mcp subagents projects skills) do (
    if not exist "%BRIDGE_DIR%\%%d" mkdir "%BRIDGE_DIR%\%%d"
)
echo       Done.

REM --- Generate token (preserve existing) ---
echo.
echo [3/4] Generating auth token...
if not exist "%TOKEN_FILE%" (
    %PYTHON% -c "import secrets; print(secrets.token_urlsafe(32))" > "%TOKEN_FILE%"
    echo       New token generated.
) else (
    echo       Existing token preserved.
)

REM --- Stop old service/task if running ---
echo.
echo [4/4] Installing and starting service...

REM Kill any existing bridge process on our port
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT% "') do (
    taskkill /F /PID %%P >nul 2>nul
)

where nssm >nul 2>&1
if not errorlevel 1 (
    REM NSSM available - install as proper Windows service
    nssm stop ArenaUnifiedBridge >nul 2>&1
    nssm remove ArenaUnifiedBridge confirm >nul 2>&1
    nssm install ArenaUnifiedBridge "%PYTHON%w" "-u %BRIDGE_DIR%\unified_bridge.py serve --root %USERPROFILE% --profile %PROFILE% --token-file %TOKEN_FILE% --port %PORT%" >nul 2>&1
    nssm set ArenaUnifiedBridge AppDirectory "%BRIDGE_DIR%" >nul 2>&1
    nssm set ArenaUnifiedBridge DisplayName "Arena Unified Bridge" >nul 2>&1
    nssm set ArenaUnifiedBridge Start SERVICE_AUTO_START >nul 2>&1
    nssm set ArenaUnifiedBridge AppStdout "%BRIDGE_DIR%\logs\bridge.log" >nul 2>&1
    nssm set ArenaUnifiedBridge AppStderr "%BRIDGE_DIR%\logs\bridge_err.log" >nul 2>&1
    nssm start ArenaUnifiedBridge >nul 2>&1
    echo [OK] NSSM service installed and started.
) else (
    REM No NSSM - use Scheduled Task
    echo @echo off > "%BRIDGE_DIR%\start_bridge.bat"
    echo cd /d "%BRIDGE_DIR%" >> "%BRIDGE_DIR%\start_bridge.bat"
    echo %PYTHON% -u unified_bridge.py serve --root "%USERPROFILE%" --profile %PROFILE% --token-file token.txt --port %PORT% >> "%BRIDGE_DIR%\start_bridge.bat"
    
    schtasks /delete /tn "ArenaUnifiedBridge" /f >nul 2>&1
    schtasks /create /tn "ArenaUnifiedBridge" /tr "%BRIDGE_DIR%\start_bridge.bat" /sc onstart /ru "%USERNAME%" /rl highest /f >nul 2>&1
    schtasks /run /tn "ArenaUnifiedBridge" >nul 2>&1
    echo [OK] Scheduled task installed and started.
)

REM --- Wait and verify ---
timeout /t 3 /nobreak >nul

echo.
echo  ========================================
echo   Installation Complete!
echo  ========================================
echo.
echo   Dashboard:  http://127.0.0.1:%PORT%/gui
echo   Health:     http://127.0.0.1:%PORT%/health
echo   Token file: %TOKEN_FILE%
echo.

REM Show token
if exist "%TOKEN_FILE%" (
    echo   Your auth token:
    for /f "delims=" %%t in ('type "%TOKEN_FILE%"') do echo   %%t
    echo.
)

echo   Optional: tailscale funnel --bg %PORT%
echo.
pause
