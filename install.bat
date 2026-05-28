@echo off
REM ============================================================
REM  Arena Unified Bridge — Universal Windows Installer
REM  Everything stays in this directory. No scattered files.
REM  Run:  install.bat
REM ============================================================
setlocal enabledelayedexpansion

echo.
echo  ========================================
echo   Arena Unified Bridge - Installer
echo  ========================================
echo.

REM --- All paths are inside THIS directory ---
set "BRIDGE_DIR=%~dp0"
set "BRIDGE_DIR=%BRIDGE_DIR:~0,-1%"
set "PORT=8765"
set "PROFILE=owner-shell"
set "TOKEN_FILE=%BRIDGE_DIR%\token.txt"

REM --- Find Python (try multiple names) ---
set "PYTHON="
for %%c in (python python3 py) do (
    if not defined PYTHON (
        %%c --version >nul 2>&1
        if not errorlevel 1 set "PYTHON=%%c"
    )
)
if not defined PYTHON (
    echo [ERROR] Python not found. Install Python 3.10+ and add to PATH.
    echo         Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('%PYTHON% --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER% found

REM --- Read version from bridge (no hardcoded version) ---
set "VERSION=unknown"
for /f "tokens=3" %%v in ('findstr /r "^VERSION = " "%BRIDGE_DIR%\unified_bridge.py" 2^>nul') do set "VERSION=%%v"
set "VERSION=%VERSION:"=%"
echo [OK] Bridge v%VERSION%

REM --- Install dependencies ---
echo.
echo [1/4] Installing Python dependencies...
%PYTHON% -m pip install aiohttp psutil --quiet 2>nul
echo       Done.

REM --- Create subdirectories (all inside BRIDGE_DIR) ---
echo.
echo [2/4] Creating directory structure...
for %%d in (memory missions hooks\pre_skill.d hooks\post_skill.d logs queue\inbox queue\running queue\done queue\failed reports\shots backups mcp subagents projects skills scripts bin) do (
    if not exist "%BRIDGE_DIR%\%%d" mkdir "%BRIDGE_DIR%\%%d"
)
echo       Done.

REM --- Migration from old versions ---
set "FOUND_OLD=0"
for %%d in ("%USERPROFILE%\.arena-local-bridge" "%USERPROFILE%\.arena-agent" "%USERPROFILE%\arena-agent") do (
    if exist "%%d" set "FOUND_OLD=1"
)
if "%FOUND_OLD%"=="1" (
    echo.
    echo  ========================================
    echo   Migration from Old Versions
    echo  ========================================
    echo.
    for %%d in ("%USERPROFILE%\.arena-local-bridge" "%USERPROFILE%\.arena-agent" "%USERPROFILE%\arena-agent") do (
        if exist "%%d" (
            echo [INFO] Found old directory: %%d
            REM Migrate token if not already present
            if exist "%%d\token.txt" if not exist "%TOKEN_FILE%" (
                copy "%%d\token.txt" "%TOKEN_FILE%" >nul 2>&1
                echo [OK] Token migrated from %%d
            )
            REM Migrate audit if not already present
            if exist "%%d\audit.jsonl" if not exist "%BRIDGE_DIR%\audit.jsonl" (
                copy "%%d\audit.jsonl" "%BRIDGE_DIR%\audit.jsonl" >nul 2>&1
                echo [OK] Audit log migrated from %%d
            )
            set /p "REMOVE_OLD=Remove old directory %%d? [y/N]: "
            if /i "!REMOVE_OLD!"=="y" (
                rmdir /s /q "%%d" 2>nul
                echo [OK] Removed %%d
            )
        )
    )
    echo [OK] Migration check complete
)

REM --- Generate token (preserve existing) ---
echo.
echo [3/4] Generating auth token...
if not exist "%TOKEN_FILE%" (
    %PYTHON% -c "import secrets; print(secrets.token_urlsafe(32))" > "%TOKEN_FILE%"
    echo       New token generated.
) else (
    echo       Existing token preserved.
)

REM ============================================================
REM Optional Components
REM ============================================================
echo.
echo  ========================================
echo   Optional Components
echo  ========================================
echo.

REM --- Tailscale ---
where tailscale >nul 2>&1
if not errorlevel 1 (
    REM Check if logged in
    tailscale status >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Tailscale is installed but not logged in
        set /p "TS_LOGIN=Run Tailscale login now? [y/N]: "
        if /i "!TS_LOGIN!"=="y" (
            tailscale login
            echo [OK] Tailscale login initiated - follow the URL in output
        ) else (
            echo [INFO] You can login later: tailscale login
        )
    ) else (
        echo [OK] Tailscale found and logged in - funnel available
    )
) else (
    echo [INFO] Tailscale not found. Install for internet access: https://tailscale.com
)

REM --- SuperPowers ---
if exist "%BRIDGE_DIR%\skills\superpowers\skills" (
    echo [OK] SuperPowers already installed in skills\superpowers\
) else (
    set /p "INSTALL_SP=Install SuperPowers? (agentic TDD, debugging, planning skills) [y/N]: "
    if /i "!INSTALL_SP!"=="y" (
        echo [INFO] Cloning SuperPowers from GitHub...
        git clone --depth 1 https://github.com/obra/superpowers.git "%BRIDGE_DIR%\skills\superpowers" 2>nul
        if exist "%BRIDGE_DIR%\skills\superpowers\skills" (
            echo [OK] SuperPowers installed - 14 skills available
        ) else (
            echo [WARN] SuperPowers clone failed. Install later:
            echo        git clone https://github.com/obra/superpowers.git "%BRIDGE_DIR%\skills\superpowers"
        )
    ) else (
        echo [INFO] SuperPowers skipped. Install later:
        echo        git clone https://github.com/obra/superpowers.git "%BRIDGE_DIR%\skills\superpowers"
    )
)

REM --- BrowserAct ---
where browser-act >nul 2>&1
if not errorlevel 1 (
    echo [OK] BrowserAct already installed
) else (
    where uv >nul 2>&1
    if not errorlevel 1 (
        set /p "INSTALL_BA=Install BrowserAct? (browser automation CLI for AI agents) [y/N]: "
        if /i "!INSTALL_BA!"=="y" (
            echo [INFO] Installing BrowserAct via uv (requires Python 3.12)...
            uv tool install browser-act-cli --python 3.12 2>nul
            where browser-act >nul 2>&1
            if not errorlevel 1 (
                echo [OK] BrowserAct installed
                if not exist "%BRIDGE_DIR%\skills\browseract" mkdir "%BRIDGE_DIR%\skills\browseract"
                if not exist "%BRIDGE_DIR%\skills\browseract\SKILL.md" (
                    echo [INFO] Downloading BrowserAct skill file...
                    curl -fsSL "https://raw.githubusercontent.com/browser-act/skills/main/browser-act/SKILL.md" -o "%BRIDGE_DIR%\skills\browseract\SKILL.md" 2>nul
                )
            ) else (
                echo [WARN] BrowserAct installation may have failed. Install manually:
                echo        uv tool install browser-act-cli --python 3.12
            )
        ) else (
            echo [INFO] BrowserAct skipped. Install later:
            echo        uv tool install browser-act-cli --python 3.12
        )
    ) else (
        echo [INFO] BrowserAct requires 'uv' package manager. Install uv first:
        echo        https://docs.astral.sh/uv/getting-started/installation/
        echo        Then: uv tool install browser-act-cli --python 3.12
    )
)

echo.

REM ============================================================
REM Step 4: Install and start service
REM ============================================================
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

    REM Determine pythonw path (no console window)
    set "PYW=%PYTHON%"
    for %%p in ("%PYTHON%") do set "PYW=%%~dpPpythonw%%~xP"
    if not exist "!PYW!" set "PYW=%PYTHON%"

    nssm install ArenaUnifiedBridge "!PYW!" "-u %BRIDGE_DIR%\unified_bridge.py serve --root %USERPROFILE% --profile %PROFILE% --port %PORT%" >nul 2>&1
    nssm set ArenaUnifiedBridge AppDirectory "%BRIDGE_DIR%" >nul 2>&1
    nssm set ArenaUnifiedBridge DisplayName "Arena Unified Bridge v%VERSION%" >nul 2>&1
    nssm set ArenaUnifiedBridge Start SERVICE_AUTO_START >nul 2>&1
    nssm set ArenaUnifiedBridge AppStdout "%BRIDGE_DIR%\logs\bridge.log" >nul 2>&1
    nssm set ArenaUnifiedBridge AppStderr "%BRIDGE_DIR%\logs\bridge_err.log" >nul 2>&1
    nssm set ArenaUnifiedBridge AppEnvironmentExtra ARENA_AGENT_HOME=%BRIDGE_DIR% ARENA_TOKEN_FILE=%TOKEN_FILE% >nul 2>&1
    nssm start ArenaUnifiedBridge >nul 2>&1
    echo [OK] NSSM service installed and started.
) else (
    REM No NSSM - use Scheduled Task
    echo @echo off > "%BRIDGE_DIR%\start_bridge.bat"
    echo cd /d "%BRIDGE_DIR%" >> "%BRIDGE_DIR%\start_bridge.bat"
    echo set ARENA_AGENT_HOME=%BRIDGE_DIR% >> "%BRIDGE_DIR%\start_bridge.bat"
    echo set ARENA_TOKEN_FILE=token.txt >> "%BRIDGE_DIR%\start_bridge.bat"
    echo %PYTHON% -u unified_bridge.py serve --root "%USERPROFILE%" --profile %PROFILE% --port %PORT% >> "%BRIDGE_DIR%\start_bridge.bat"

    schtasks /delete /tn "ArenaUnifiedBridge" /f >nul 2>&1
    schtasks /create /tn "ArenaUnifiedBridge" /tr "%BRIDGE_DIR%\start_bridge.bat" /sc onstart /ru "%USERNAME%" /rl highest /f >nul 2>&1
    schtasks /run /tn "ArenaUnifiedBridge" >nul 2>&1
    echo [OK] Scheduled task installed and started.
)

REM --- Wait and verify ---
echo [INFO] Waiting for bridge to start...
for /L %%i in (1,1,10) do (
    curl -fsS "http://127.0.0.1:%PORT%/health" >nul 2>&1
    if not errorlevel 1 (
        echo [OK] Bridge is healthy! v%VERSION%
        goto :healthy
    )
    timeout /t 1 /nobreak >nul
)
echo [WARN] Bridge not responding after 10s. Check: %BRIDGE_DIR%\logs\bridge.log
:healthy

echo.
echo  ========================================
echo   Installation Complete!
echo  ========================================
echo.
echo   Directory:  %BRIDGE_DIR%
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

echo   Manage:
where nssm >nul 2>&1
if not errorlevel 1 (
    echo     nssm status ArenaUnifiedBridge
    echo     nssm restart ArenaUnifiedBridge
    echo     nssm stop ArenaUnifiedBridge
) else (
    echo     schtasks /run /tn "ArenaUnifiedBridge"
    echo     schtasks /end /tn "ArenaUnifiedBridge"
)
echo.
echo   Optional:
echo   tailscale funnel --bg %PORT%
echo.
echo   Installed skills:
if exist "%BRIDGE_DIR%\skills\superpowers" echo   SuperPowers   - %BRIDGE_DIR%\skills\superpowers\
if exist "%BRIDGE_DIR%\skills\browseract" echo   BrowserAct    - %BRIDGE_DIR%\skills\browseract\
echo.
echo   Update: re-run install.bat or: cd %BRIDGE_DIR% ^&^& git pull
echo.
pause
