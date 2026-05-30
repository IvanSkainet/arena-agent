@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  Arena Unified Bridge — Windows Installer v2.0.6
REM  Full parity with install.sh. Window stays open on errors.
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
echo [1/6] Finding Python...
set "PYTHON="
where python >nul 2>&1
if not errorlevel 1 set "PYTHON=python"
if not defined PYTHON where python3 >nul 2>&1
if not defined PYTHON if not errorlevel 1 set "PYTHON=python3"
if not defined PYTHON where py >nul 2>&1
if not defined PYTHON if not errorlevel 1 set "PYTHON=py"
if not defined PYTHON (
    echo.
    echo  [ERROR] Python not found!
    echo  Install Python 3.10+ and add to PATH.
    echo  Download: https://www.python.org/downloads/
    echo  Check "Add Python to PATH" during install.
    echo.
    goto :end
)
for /f "delims=" %%v in ('%PYTHON% --version 2^>^&1') do echo       %%v found

REM --- Read version: write a tiny .py helper to avoid all CMD escaping issues ---
echo t=open(r'%BRIDGE_DIR%\unified_bridge.py',encoding='utf-8').read()>"%TEMP%\arena_ver.py"
echo i=t.find('VERSION = ')>>"%TEMP%\arena_ver.py"
echo q1=t.find(chr(34),i)+1>>"%TEMP%\arena_ver.py"
echo q2=t.find(chr(34),q1)>>"%TEMP%\arena_ver.py"
echo print(t[q1:q2]if q1^>0 and q2^>0 else'unknown')>>"%TEMP%\arena_ver.py"
%PYTHON% "%TEMP%\arena_ver.py" >"%TEMP%\arena_ver.txt" 2>nul
set /p "VERSION=" <"%TEMP%\arena_ver.txt"
del "%TEMP%\arena_ver.py" "%TEMP%\arena_ver.txt" >nul 2>&1
echo       Bridge v!VERSION!

REM ============================================================
REM Step 2: Install Python dependencies
REM ============================================================
echo.
echo [2/6] Installing Python dependencies...
%PYTHON% -m pip install --quiet aiohttp psutil 2>nul
if errorlevel 1 %PYTHON% -m pip install --quiet --user aiohttp psutil 2>nul
echo       Done.

REM ============================================================
REM Step 3: Create directories + token
REM ============================================================
echo.
echo [3/6] Creating directory structure...
for %%d in (memory missions hooks hooks\pre_skill.d hooks\post_skill.d logs queue queue\inbox queue\running queue\done queue\failed reports reports\shots backups mcp subagents projects skills scripts bin) do (
    if not exist "%BRIDGE_DIR%\%%d" mkdir "%BRIDGE_DIR%\%%d"
)
echo       Done.

if not exist "%TOKEN_FILE%" (
    %PYTHON% -c "import secrets;print(secrets.token_urlsafe(32),end='')" >"%TOKEN_FILE%"
    echo       New auth token generated.
) else (
    echo       Existing token preserved.
)

set "AUTH_TOKEN="
if exist "%TOKEN_FILE%" set /p "AUTH_TOKEN=" <"%TOKEN_FILE%"

REM ============================================================
REM Step 4: Optional Components
REM ============================================================
echo.
echo  ========================================
echo   Optional Components
echo  ========================================
echo.

REM --- Tailscale ---
where tailscale >nul 2>&1
if errorlevel 1 (
    echo [INFO] Tailscale not found. Install: https://tailscale.com
    goto :tailscale_done
)
echo [OK] Tailscale is installed
set "TS_URL="
for /f "delims=" %%u in ('tailscale status --json 2^>nul ^| %PYTHON% -c "import json,sys;d=json.load(sys.stdin);dns=d.get('Self',{}).get('DNSName','')or d.get('DNSName','');print(dns.rstrip('.'))if dns else''" 2^>nul') do set "TS_URL=%%u"
if not defined TS_URL (
    echo [WARN] Tailscale installed but not logged in. Run: tailscale login
    goto :tailscale_done
)
echo [OK] Tailscale connected: %TS_URL%
:tailscale_done

REM --- SuperPowers ---
if exist "%BRIDGE_DIR%\skills\superpowers\skills" goto :sp_exists
echo [INFO] Installing SuperPowers from GitHub...
git clone --depth 1 https://github.com/obra/superpowers.git "%BRIDGE_DIR%\skills\superpowers" >nul 2>&1
if exist "%BRIDGE_DIR%\skills\superpowers\skills" (
    echo [OK] SuperPowers installed
) else (
    echo [WARN] SuperPowers clone failed. Install later:
    echo        git clone https://github.com/obra/superpowers.git skills\superpowers
)
goto :sp_done
:sp_exists
for /f %%c in ('dir /b "%BRIDGE_DIR%\skills\superpowers\skills" 2^>nul ^| find /c /v ""') do echo [OK] SuperPowers already installed - %%c skills
:sp_done

REM --- BrowserAct ---
where browser-act >nul 2>&1
if not errorlevel 1 (
    echo [OK] BrowserAct already installed
    goto :ba_done
)
where uv >nul 2>&1
if errorlevel 1 (
    echo [INFO] BrowserAct requires uv. Install: https://docs.astral.sh/uv/getting-started/installation/
    goto :ba_done
)
echo [INFO] Installing BrowserAct via uv...
uv tool install browser-act-cli --python 3.12 >nul 2>&1
where browser-act >nul 2>&1
if errorlevel 1 (
    echo [WARN] BrowserAct install may have failed. Try: uv tool install browser-act-cli --python 3.12
    goto :ba_done
)
echo [OK] BrowserAct installed
if not exist "%BRIDGE_DIR%\skills\browseract" mkdir "%BRIDGE_DIR%\skills\browseract"
if not exist "%BRIDGE_DIR%\skills\browseract\SKILL.md" curl --max-time 10 -fsSL "https://raw.githubusercontent.com/browser-act/skills/main/browser-act/SKILL.md" -o "%BRIDGE_DIR%\skills\browseract\SKILL.md" 2>nul
:ba_done

REM --- Camoufox ---
where browser-act >nul 2>&1
if errorlevel 1 goto :camoufox_done
echo [INFO] Checking Camoufox stealth browser...
%PYTHON% -c "import camoufox;print('ok')" >nul 2>&1
if not errorlevel 1 (
    echo [OK] Camoufox stealth browser ready
    goto :camoufox_done
)
%PYTHON% -m camoufox fetch >nul 2>&1
echo       Done.
:camoufox_done

echo.

REM ============================================================
REM Step 5: Install and start bridge service
REM ============================================================
echo [4/6] Installing as system service...

REM Stop any existing bridge service/task BEFORE killing processes
schtasks /end /tn "ArenaUnifiedBridge" >nul 2>&1
where nssm >nul 2>&1
if not errorlevel 1 nssm stop ArenaUnifiedBridge >nul 2>&1
ping -n 2 127.0.0.1 >nul

REM Kill any remaining bridge processes on our port
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT% "') do taskkill /F /PID %%P >nul 2>nul
ping -n 2 127.0.0.1 >nul

REM Create start_bridge.bat (for manual use and schtasks)
echo @echo off> "%BRIDGE_DIR%\start_bridge.bat"
echo cd /d "%BRIDGE_DIR%">> "%BRIDGE_DIR%\start_bridge.bat"
echo set ARENA_AGENT_HOME=%BRIDGE_DIR%>> "%BRIDGE_DIR%\start_bridge.bat"
echo set ARENA_TOKEN_FILE=%TOKEN_FILE%>> "%BRIDGE_DIR%\start_bridge.bat"
echo %PYTHON% -u unified_bridge.py serve --root "%USERPROFILE%" --profile %PROFILE% --port %PORT%>> "%BRIDGE_DIR%\start_bridge.bat"

REM Create start_hidden.vbs (launches start_bridge.bat with NO visible window)
echo Set WshShell = CreateObject^("WScript.Shell"^)> "%BRIDGE_DIR%\start_hidden.vbs"
echo WshShell.Run """%BRIDGE_DIR%\start_bridge.bat""", 0, False>> "%BRIDGE_DIR%\start_hidden.vbs"

set "SERVICE_METHOD=none"

where nssm >nul 2>&1
if not errorlevel 1 goto :use_nssm

:use_schtasks
set "SERVICE_METHOD=schtasks"
echo       NSSM not found, using Scheduled Task with hidden window...

schtasks /delete /tn "ArenaUnifiedBridge" /f >nul 2>&1
schtasks /create /tn "ArenaUnifiedBridge" /tr "wscript.exe \"%BRIDGE_DIR%\start_hidden.vbs\"" /sc onstart /ru "%USERNAME%" /rl highest /f >nul 2>&1
schtasks /run /tn "ArenaUnifiedBridge" >nul 2>&1
echo       [OK] Scheduled task installed and started.
goto :service_installed

:use_nssm
set "SERVICE_METHOD=nssm"
echo       Using NSSM service manager...

nssm remove ArenaUnifiedBridge confirm >nul 2>&1

REM Find pythonw.exe (no console window) for NSSM
set "PYW=%PYTHON%"
for %%p in ("%PYTHON%") do (
    if exist "%%~dpPpythonw%%~xP" set "PYW=%%~dpPpythonw%%~xP"
)

nssm install ArenaUnifiedBridge "!PYW!" "-u %BRIDGE_DIR%\unified_bridge.py serve --root %USERPROFILE% --profile %PROFILE% --port %PORT%" >nul 2>&1
nssm set ArenaUnifiedBridge AppDirectory "%BRIDGE_DIR%" >nul 2>&1
nssm set ArenaUnifiedBridge DisplayName "Arena Unified Bridge v!VERSION!" >nul 2>&1
nssm set ArenaUnifiedBridge Start SERVICE_AUTO_START >nul 2>&1
nssm set ArenaUnifiedBridge AppStdout "%BRIDGE_DIR%\logs\bridge.log" >nul 2>&1
nssm set ArenaUnifiedBridge AppStderr "%BRIDGE_DIR%\logs\bridge_err.log" >nul 2>&1
nssm set ArenaUnifiedBridge AppEnvironmentExtra ARENA_AGENT_HOME=%BRIDGE_DIR% ARENA_TOKEN_FILE=%TOKEN_FILE% >nul 2>&1
nssm start ArenaUnifiedBridge >nul 2>&1
echo       [OK] NSSM service installed and started.

:service_installed

REM --- Windows Firewall rule ---
netsh advfirewall firewall show rule name="Arena Bridge" >nul 2>&1
if not errorlevel 1 goto :firewall_done
netsh advfirewall firewall add rule name="Arena Bridge" dir=in action=allow protocol=TCP localport=%PORT% >nul 2>&1
if not errorlevel 1 echo       [OK] Firewall rule added for port %PORT%
:firewall_done

REM ============================================================
REM Step 6: Wait for bridge and verify
REM ============================================================
echo.
echo [5/6] Waiting for bridge to start...
set "HEALTHY=0"
for /L %%i in (1,1,30) do (
    if "!HEALTHY!"=="0" (
        curl --max-time 3 -fsS "http://127.0.0.1:%PORT%/health" >nul 2>&1
        if not errorlevel 1 (
            set "HEALTHY=1"
            echo       Bridge is healthy! v!VERSION!
        ) else (
            echo       Waiting... %%i/30
            ping -n 3 127.0.0.1 >nul
        )
    )
)
if "!HEALTHY!"=="1" goto :healthy_ok
echo.
echo  [WARN] Bridge not responding after 90 seconds.
echo.
echo  Check logs: %BRIDGE_DIR%\logs\bridge.log
echo  %BRIDGE_DIR%\logs\bridge_err.log
echo.
echo  Start manually:
echo    cd /d "%BRIDGE_DIR%"
echo    %PYTHON% -u unified_bridge.py serve --root "%USERPROFILE%" --port %PORT%
echo.
:healthy_ok

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

if not defined AUTH_TOKEN goto :no_token
echo   Your token:
echo   %AUTH_TOKEN%
echo.
echo   Dashboard with login:
echo   http://127.0.0.1:%PORT%/gui
echo.
:no_token

echo   Your secure Tailscale URL:
if not defined TS_URL echo   not configured - install Tailscale: https://tailscale.com
if defined TS_URL echo   https://%TS_URL%
echo.

echo   Manage:
if "%SERVICE_METHOD%"=="nssm" goto :manage_nssm
echo     schtasks /run /tn "ArenaUnifiedBridge"
echo     schtasks /end /tn "ArenaUnifiedBridge"
echo     Or: start_bridge.bat
goto :manage_done
:manage_nssm
echo     nssm status ArenaUnifiedBridge
echo     nssm restart ArenaUnifiedBridge
echo     nssm stop ArenaUnifiedBridge
:manage_done

echo.
echo   Optional:
echo   tailscale funnel --bg %PORT%
echo.
echo   Installed skills:
if exist "%BRIDGE_DIR%\skills\superpowers\skills" echo   SuperPowers   - skills\superpowers\
where browser-act >nul 2>&1
if not errorlevel 1 echo   BrowserAct    - installed
echo.
echo   Update:
echo   cd /d "%BRIDGE_DIR%" ^&^& git pull ^&^& install.bat
echo.

:end
echo.
pause
