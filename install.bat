@echo off
REM ============================================================
REM  Arena Unified Bridge — Windows Installer
REM  Double-click this file to install. Window stays open on errors.
REM ============================================================

REM === ANTI-CLOSE: Re-launch with cmd /k so window NEVER closes ===
if "%~1"==":RUN" goto :main
cmd /k "%~0" :RUN
exit /b

:main
echo.
echo  ========================================
echo   Arena Unified Bridge - Installer
echo  ========================================
echo.

set "BRIDGE_DIR=%~dp0"
if "%BRIDGE_DIR:~-1%"=="\" set "BRIDGE_DIR=%BRIDGE_DIR:~0,-1%"
if defined ARENA_PORT (set "PORT=%ARENA_PORT%") else (set "PORT=8765")
set "PROFILE=owner-shell"
set "TOKEN_FILE=%BRIDGE_DIR%\token.txt"

REM ============================================================
REM Step 1: Find Python
REM ============================================================
echo [1/5] Finding Python...
set "PYTHON="
for %%c in (python python3 py) do (
    if not defined PYTHON (
        %%c --version >nul 2>&1
        if not errorlevel 1 set "PYTHON=%%c"
    )
)
if not defined PYTHON (
    echo.
    echo  [ERROR] Python not found!
    echo  Install Python 3.10+ and add to PATH.
    echo  Download: https://www.python.org/downloads/
    echo  IMPORTANT: Check "Add Python to PATH" during install.
    echo.
    goto :end
)

for /f "tokens=2 delims= " %%v in ('%PYTHON% --version 2^>^&1') do set "PYVER=%%v"
echo       Python %PYVER% found

set "VERSION=unknown"
for /f "tokens=3" %%v in ('findstr /r "^VERSION = " "%BRIDGE_DIR%\unified_bridge.py" 2^>nul') do set "VERSION=%%v"
set "VERSION=%VERSION:"=%"
echo       Bridge v%VERSION%

REM ============================================================
REM Step 2: Install Python dependencies
REM ============================================================
echo.
echo [2/5] Installing Python dependencies...
%PYTHON% -m pip install --quiet aiohttp psutil 2>nul
if errorlevel 1 (
    echo       [WARN] pip install had issues, trying --user...
    %PYTHON% -m pip install --quiet --user aiohttp psutil 2>nul
)
echo       Done.

REM ============================================================
REM Step 3: Create directories + token
REM ============================================================
echo.
echo [3/5] Creating directory structure...
for %%d in (memory missions hooks hooks\pre_skill.d hooks\post_skill.d logs queue queue\inbox queue\running queue\done queue\failed reports reports\shots backups mcp subagents projects skills scripts bin) do (
    if not exist "%BRIDGE_DIR%\%%d" mkdir "%BRIDGE_DIR%\%%d"
)
echo       Done.

if not exist "%TOKEN_FILE%" (
    %PYTHON% -c "import secrets; print(secrets.token_urlsafe(32), end='')" > "%TOKEN_FILE%"
    echo       New auth token generated.
) else (
    echo       Existing token preserved.
)

set "AUTH_TOKEN="
if exist "%TOKEN_FILE%" (
    set /p "AUTH_TOKEN=" < "%TOKEN_FILE%"
)

REM ============================================================
REM Step 4: Install and start bridge service
REM ============================================================
echo.
echo [4/5] Installing bridge service...

REM Kill any existing bridge on our port
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT% "') do (
    taskkill /F /PID %%P >nul 2>nul
)

set "SERVICE_METHOD=none"

where nssm >nul 2>&1
if not errorlevel 1 (
    set "SERVICE_METHOD=nssm"
    echo       Using NSSM service manager...

    nssm stop ArenaUnifiedBridge >nul 2>&1
    ping -n 2 127.0.0.1 >nul
    nssm remove ArenaUnifiedBridge confirm >nul 2>&1

    set "PYW=%PYTHON%"
    for %%p in ("%PYTHON%") do (
        if exist "%%~dpPpythonw%%~xP" set "PYW=%%~dpPpythonw%%~xP"
    )

    nssm install ArenaUnifiedBridge "!PYW!" "-u %BRIDGE_DIR%\unified_bridge.py serve --root %USERPROFILE% --profile %PROFILE% --port %PORT%" >nul 2>&1
    nssm set ArenaUnifiedBridge AppDirectory "%BRIDGE_DIR%" >nul 2>&1
    nssm set ArenaUnifiedBridge DisplayName "Arena Unified Bridge v%VERSION%" >nul 2>&1
    nssm set ArenaUnifiedBridge Start SERVICE_AUTO_START >nul 2>&1
    nssm set ArenaUnifiedBridge AppStdout "%BRIDGE_DIR%\logs\bridge.log" >nul 2>&1
    nssm set ArenaUnifiedBridge AppStderr "%BRIDGE_DIR%\logs\bridge_err.log" >nul 2>&1
    nssm set ArenaUnifiedBridge AppEnvironmentExtra ARENA_AGENT_HOME=%BRIDGE_DIR% ARENA_TOKEN_FILE=%TOKEN_FILE% >nul 2>&1
    nssm start ArenaUnifiedBridge >nul 2>&1
    echo       [OK] NSSM service installed and started.
) else (
    set "SERVICE_METHOD=schtasks"
    echo       NSSM not found, using Scheduled Task...

    echo @echo off> "%BRIDGE_DIR%\start_bridge.bat"
    echo cd /d "%BRIDGE_DIR%">> "%BRIDGE_DIR%\start_bridge.bat"
    echo set ARENA_AGENT_HOME=%BRIDGE_DIR%>> "%BRIDGE_DIR%\start_bridge.bat"
    echo set ARENA_TOKEN_FILE=%TOKEN_FILE%>> "%BRIDGE_DIR%\start_bridge.bat"
    echo %PYTHON% -u unified_bridge.py serve --root "%USERPROFILE%" --profile %PROFILE% --port %PORT%>> "%BRIDGE_DIR%\start_bridge.bat"

    schtasks /delete /tn "ArenaUnifiedBridge" /f >nul 2>&1
    schtasks /create /tn "ArenaUnifiedBridge" /tr "%BRIDGE_DIR%\start_bridge.bat" /sc onstart /ru "%USERNAME%" /rl highest /f >nul 2>&1
    schtasks /run /tn "ArenaUnifiedBridge" >nul 2>&1
    echo       [OK] Scheduled task installed and started.
)

REM --- Windows Firewall rule ---
netsh advfirewall firewall show rule name="Arena Bridge" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="Arena Bridge" dir=in action=allow protocol=TCP localport=%PORT% >nul 2>&1
    if not errorlevel 1 echo       [OK] Firewall rule added for port %PORT%
)

REM ============================================================
REM Step 5: Wait for bridge and verify
REM ============================================================
echo.
echo [5/5] Waiting for bridge to start...
set "HEALTHY=0"
for /L %%i in (1,1,15) do (
    if "!HEALTHY!"=="0" (
        curl --max-time 2 -fsS "http://127.0.0.1:%PORT%/health" >nul 2>&1
        if not errorlevel 1 (
            set "HEALTHY=1"
            echo       Bridge is healthy! v%VERSION%
        ) else (
            <nul set /p "=      Waiting... "
            echo %%i/15
            ping -n 3 127.0.0.1 >nul
        )
    )
)
if "!HEALTHY!"=="0" (
    echo.
    echo  [WARN] Bridge not responding after 30 seconds.
    echo.
    echo  Possible causes:
    echo    - Python dependencies failed to install
    echo    - Port %PORT% is already in use
    echo    - Antivirus blocking the process
    echo.
    echo  Try starting manually:
    echo    cd /d "%BRIDGE_DIR%"
    echo    %PYTHON% -u unified_bridge.py serve --root "%USERPROFILE%" --port %PORT%
    echo.
    echo  Check logs: %BRIDGE_DIR%\logs\bridge.log
    echo.
)

REM ============================================================
REM Summary
REM ============================================================
echo.
echo  ========================================
echo   INSTALLATION COMPLETE
echo  ========================================
echo.
echo   Directory:  %BRIDGE_DIR%
echo   Dashboard:  http://127.0.0.1:%PORT%/gui
echo   Health:     http://127.0.0.1:%PORT%/health
echo   Token file: %TOKEN_FILE%
echo.

if defined AUTH_TOKEN (
    echo   Your auth token:
    echo   %AUTH_TOKEN%
    echo.
    echo   Dashboard (with auth):
    echo   http://127.0.0.1:%PORT%/gui?token=%AUTH_TOKEN%
    echo.
)

echo   Manage:
if "%SERVICE_METHOD%"=="nssm" (
    echo     nssm status ArenaUnifiedBridge
    echo     nssm restart ArenaUnifiedBridge
    echo     nssm stop ArenaUnifiedBridge
) else (
    echo     schtasks /run /tn "ArenaUnifiedBridge"
    echo     schtasks /end /tn "ArenaUnifiedBridge"
    echo     Or: start_bridge.bat
)
echo.
echo   Logs: %BRIDGE_DIR%\logs\bridge.log
echo   Update: cd /d "%BRIDGE_DIR%" ^&^& git pull ^&^& install.bat
echo.

:end
echo.
pause
