@echo off
REM ============================================================
REM  Arena Local Agent - Universal Installer (Windows)
REM
REM  Cross-version, cross-Python, no hardcoded paths.
REM  Detects everything dynamically. Asks before regenerating token.
REM
REM  Env overrides (all optional):
REM    ARENA_HOME       default: %USERPROFILE%\arena-agent
REM    BRIDGE_HOME      default: %USERPROFILE%\arena-local-bridge
REM    ARENA_PORT       default: 8765
REM    ARENA_PROFILE    default: owner-shell
REM    ARENA_TASK_NAME  default: ArenaUnifiedBridge
REM                     (use a different name for test installations)
REM    ARENA_DRY_RUN    if 1: only checks env, writes nothing, restarts nothing
REM    ARENA_NO_TASK    if 1: skip Scheduled Task creation
REM    ARENA_NO_RESTART if 1: skip killing/restarting processes
REM    ARENA_REGEN_TOKEN  Y / N   override token-regen prompt
REM
REM  CLI flags:
REM    --check-only / --dry-run   same as ARENA_DRY_RUN=1
REM    --no-task                  same as ARENA_NO_TASK=1
REM    --no-restart               same as ARENA_NO_RESTART=1
REM    --keep-token               same as ARENA_REGEN_TOKEN=N
REM    --regen-token              same as ARENA_REGEN_TOKEN=Y
REM ============================================================

setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

REM === Parse CLI flags ===
:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--check-only"  set "ARENA_DRY_RUN=1"
if /I "%~1"=="--dry-run"     set "ARENA_DRY_RUN=1"
if /I "%~1"=="--no-task"     set "ARENA_NO_TASK=1"
if /I "%~1"=="--no-restart"  set "ARENA_NO_RESTART=1"
if /I "%~1"=="--keep-token"  set "ARENA_REGEN_TOKEN=N"
if /I "%~1"=="--regen-token" set "ARENA_REGEN_TOKEN=Y"
shift
goto :parse_args
:args_done

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM Trim USERPROFILE (some envs leave trailing spaces from "set X=Y && ...")
for /f "tokens=* delims= " %%A in ("%USERPROFILE%") do set "USERPROFILE=%%A"

REM Defaults
if not defined ARENA_HOME       set "ARENA_HOME=%USERPROFILE%\arena-agent"
if not defined BRIDGE_HOME      set "BRIDGE_HOME=%USERPROFILE%\arena-local-bridge"
if not defined ARENA_PORT       set "ARENA_PORT=8765"
if not defined ARENA_PROFILE    set "ARENA_PROFILE=owner-shell"
if not defined ARENA_TASK_NAME  set "ARENA_TASK_NAME=ArenaUnifiedBridge"
if not defined ARENA_DRY_RUN    set "ARENA_DRY_RUN=0"
if not defined ARENA_NO_TASK    set "ARENA_NO_TASK=0"
if not defined ARENA_NO_RESTART set "ARENA_NO_RESTART=0"

REM Trim again (in case env vars came in with whitespace)
for /f "tokens=* delims= " %%A in ("%ARENA_HOME%")      do set "ARENA_HOME=%%A"
for /f "tokens=* delims= " %%A in ("%BRIDGE_HOME%")     do set "BRIDGE_HOME=%%A"
for /f "tokens=* delims= " %%A in ("%ARENA_PORT%")      do set "ARENA_PORT=%%A"
for /f "tokens=* delims= " %%A in ("%ARENA_PROFILE%")   do set "ARENA_PROFILE=%%A"
for /f "tokens=* delims= " %%A in ("%ARENA_TASK_NAME%") do set "ARENA_TASK_NAME=%%A"

echo ============================================================
echo   Arena Local Agent - Universal Installer
echo ============================================================
echo   Script dir : %SCRIPT_DIR%
echo   Bridge home: %BRIDGE_HOME%
echo   Agent home : %ARENA_HOME%
echo   Port       : %ARENA_PORT%
echo   Profile    : %ARENA_PROFILE%
echo   Task name  : %ARENA_TASK_NAME%
echo   Dry run    : %ARENA_DRY_RUN%
echo   No task    : %ARENA_NO_TASK%
echo   No restart : %ARENA_NO_RESTART%
echo ============================================================
echo.

set "HAD_ERROR=0"

REM === 1. Find Python ===
set "PY="
set "PYW="
for %%X in (python.exe python3.exe py.exe python.cmd python.bat) do (
    if not defined PY (
        for /f "delims=" %%I in ('where %%X 2^>nul') do (
            if not defined PY set "PY=%%I"
        )
    )
)
if not defined PY (
    echo [ERROR] Python not found in PATH. Install Python 3.10+ from https://python.org
    set "HAD_ERROR=1"
    goto :final_check
)
echo [OK] Python: %PY%

for %%D in ("%PY%") do set "PYDIR=%%~dpD"
if exist "%PYDIR%pythonw.exe" (
    set "PYW=%PYDIR%pythonw.exe"
    echo [OK] PythonW: !PYW!
) else (
    set "PYW=%PY%"
    echo [WARN] pythonw.exe not found, fallback to python.exe ^(console window will appear^)
)

for /f "tokens=2" %%V in ('"%PY%" --version 2^>^&1') do set "PYVER=%%V"
echo [OK] Python version: %PYVER%

REM === 2. Check source files in SCRIPT_DIR ===
set "HAVE_BRIDGE_SRC=0"
set "HAVE_DASH_SRC=0"
if exist "%SCRIPT_DIR%\unified_bridge.py" set "HAVE_BRIDGE_SRC=1"
if exist "%SCRIPT_DIR%\dashboard\index.html" set "HAVE_DASH_SRC=1"
if exist "%SCRIPT_DIR%\index.html" set "HAVE_DASH_SRC=1"

echo [INFO] Source files in script dir:
echo        unified_bridge.py : %HAVE_BRIDGE_SRC%
echo        dashboard         : %HAVE_DASH_SRC%

REM === 3. Locate _arena_helper.py ===
set "HELPER="
if exist "%SCRIPT_DIR%\_arena_helper.py" set "HELPER=%SCRIPT_DIR%\_arena_helper.py"
if not defined HELPER if exist "%BRIDGE_HOME%\_arena_helper.py" set "HELPER=%BRIDGE_HOME%\_arena_helper.py"

REM === 4. Detect versions (use temp-file pattern - for /f cannot parse quoted-args reliably) ===
set "INSTALLED_VERSION=missing"
set "SOURCE_VERSION=n/a"
if defined HELPER (
    set "VTMP=%TEMP%\arena_ver_%RANDOM%%RANDOM%.txt"
    "%PY%" "!HELPER!" version "%BRIDGE_HOME%\unified_bridge.py" > "!VTMP!" 2>nul
    set "INSTALLED_VERSION="
    set /p "INSTALLED_VERSION=" < "!VTMP!"
    if not defined INSTALLED_VERSION set "INSTALLED_VERSION=missing"
    if "%HAVE_BRIDGE_SRC%"=="1" (
        "%PY%" "!HELPER!" version "%SCRIPT_DIR%\unified_bridge.py" > "!VTMP!" 2>nul
        set "SOURCE_VERSION="
        set /p "SOURCE_VERSION=" < "!VTMP!"
        if not defined SOURCE_VERSION set "SOURCE_VERSION=n/a"
    )
    del "!VTMP!" 2>nul
) else (
    echo [WARN] _arena_helper.py not found - skipping version detection
)
echo [INFO] Installed bridge version: !INSTALLED_VERSION!
echo [INFO] Source   bridge version: !SOURCE_VERSION!

REM === 5. Check current bridge health (informational) ===
curl -s -o nul -w "%%{http_code}" --max-time 2 http://127.0.0.1:%ARENA_PORT%/health > "%TEMP%\arena_pre_hc.txt" 2>nul
set /p "PREHC=" < "%TEMP%\arena_pre_hc.txt"
del "%TEMP%\arena_pre_hc.txt" 2>nul
if "%PREHC%"=="200" (
    echo [INFO] Bridge already running on port %ARENA_PORT% ^(HTTP 200^)
) else (
    echo [INFO] Bridge NOT responding on port %ARENA_PORT% ^(HTTP=%PREHC%^)
)

REM === DRY RUN: stop here ===
if "%ARENA_DRY_RUN%"=="1" (
    echo.
    echo ============================================================
    echo   DRY RUN - no changes were made.
    echo ============================================================
    goto :end_ok
)

REM === Validate we have source if bridge is missing ===
if "%HAVE_BRIDGE_SRC%"=="0" (
    if not exist "%BRIDGE_HOME%\unified_bridge.py" (
        echo [ERROR] unified_bridge.py not found in %SCRIPT_DIR%
        echo         and not already installed in %BRIDGE_HOME%
        echo         Cannot proceed.
        set "HAD_ERROR=1"
        goto :final_check
    )
)

REM === 6. Create directories ===
if not exist "%BRIDGE_HOME%"            mkdir "%BRIDGE_HOME%"
if not exist "%ARENA_HOME%"             mkdir "%ARENA_HOME%"
if not exist "%ARENA_HOME%\bin"         mkdir "%ARENA_HOME%\bin"
if not exist "%ARENA_HOME%\scripts"     mkdir "%ARENA_HOME%\scripts"
if not exist "%ARENA_HOME%\dashboard"   mkdir "%ARENA_HOME%\dashboard"
if not exist "%ARENA_HOME%\logs"        mkdir "%ARENA_HOME%\logs"
if not exist "%ARENA_HOME%\queue"       mkdir "%ARENA_HOME%\queue"
if not exist "%ARENA_HOME%\queue\inbox" mkdir "%ARENA_HOME%\queue\inbox"
if not exist "%ARENA_HOME%\memory"      mkdir "%ARENA_HOME%\memory"
if not exist "%ARENA_HOME%\missions"    mkdir "%ARENA_HOME%\missions"
if not exist "%ARENA_HOME%\reports"     mkdir "%ARENA_HOME%\reports"
echo [OK] Directories ready

REM === 7. Copy source files ===
if "%HAVE_BRIDGE_SRC%"=="1" (
    copy /Y "%SCRIPT_DIR%\unified_bridge.py" "%BRIDGE_HOME%\unified_bridge.py" >nul
    echo [OK] Copied unified_bridge.py
) else (
    echo [OK] Using existing unified_bridge.py at %BRIDGE_HOME%
)

if exist "%SCRIPT_DIR%\_arena_helper.py" (
    copy /Y "%SCRIPT_DIR%\_arena_helper.py" "%BRIDGE_HOME%\_arena_helper.py" >nul
    echo [OK] Copied _arena_helper.py
)

if exist "%SCRIPT_DIR%\dashboard\index.html" (
    copy /Y "%SCRIPT_DIR%\dashboard\index.html" "%ARENA_HOME%\dashboard\index.html" >nul
    copy /Y "%SCRIPT_DIR%\dashboard\index.html" "%BRIDGE_HOME%\index.html" >nul
    echo [OK] Copied dashboard/index.html
) else if exist "%SCRIPT_DIR%\index.html" (
    copy /Y "%SCRIPT_DIR%\index.html" "%ARENA_HOME%\dashboard\index.html" >nul
    copy /Y "%SCRIPT_DIR%\index.html" "%BRIDGE_HOME%\index.html" >nul
    echo [OK] Copied index.html
)

if exist "%SCRIPT_DIR%\bin\" (
    xcopy /Y /E /I /Q "%SCRIPT_DIR%\bin\*" "%ARENA_HOME%\bin\" >nul
    echo [OK] Copied bin/
)
if exist "%SCRIPT_DIR%\scripts\" (
    xcopy /Y /E /I /Q "%SCRIPT_DIR%\scripts\*" "%ARENA_HOME%\scripts\" >nul
    echo [OK] Copied scripts/
)

REM Re-locate helper after copy (in case it was missing from SCRIPT_DIR)
if not defined HELPER if exist "%BRIDGE_HOME%\_arena_helper.py" set "HELPER=%BRIDGE_HOME%\_arena_helper.py"

REM Re-detect final installed version (use temp file)
set "FINAL_VERSION=%SOURCE_VERSION%"
if defined HELPER (
    set "VTMP=%TEMP%\arena_fv_%RANDOM%%RANDOM%.txt"
    "%PY%" "!HELPER!" version "%BRIDGE_HOME%\unified_bridge.py" > "!VTMP!" 2>nul
    set "FINAL_VERSION="
    set /p "FINAL_VERSION=" < "!VTMP!"
    if not defined FINAL_VERSION set "FINAL_VERSION=%SOURCE_VERSION%"
    del "!VTMP!" 2>nul
)
echo [OK] Bridge version after install: !FINAL_VERSION!

REM === 8. Install Python dependencies ===
echo.
echo === Installing Python dependencies ===
"%PY%" -m pip install --quiet --upgrade pip 2>nul
"%PY%" -m pip install --quiet aiohttp 2>nul
if errorlevel 1 (
    echo [WARN] aiohttp quiet install failed, retrying verbose...
    "%PY%" -m pip install aiohttp
)
echo [OK] Python dependencies ready

REM === 9. Token handling ===
set "TOKEN_PATH=%BRIDGE_HOME%\token.txt"
set "DO_GEN=0"

if not exist "%TOKEN_PATH%" (
    set "DO_GEN=1"
    echo [INFO] No token file - will generate a new one
) else (
    if defined ARENA_REGEN_TOKEN (
        if /I "!ARENA_REGEN_TOKEN!"=="Y" set "DO_GEN=1"
        if /I "!ARENA_REGEN_TOKEN!"=="YES" set "DO_GEN=1"
        if /I "!ARENA_REGEN_TOKEN!"=="N" set "DO_GEN=0"
        if /I "!ARENA_REGEN_TOKEN!"=="NO" set "DO_GEN=0"
        echo [INFO] Token policy from env: !ARENA_REGEN_TOKEN!
    ) else (
        echo.
        echo [!] Existing token found at: %TOKEN_PATH%
        set "REGEN=Y"
        set /p "REGEN=Regenerate token? Old token will stop working [Y/n]: "
        if "!REGEN!"=="" set "REGEN=Y"
        if /I "!REGEN!"=="Y" set "DO_GEN=1"
        if /I "!REGEN!"=="YES" set "DO_GEN=1"
    )
)

if "%DO_GEN%"=="0" goto :token_keep

REM Generate token via temp file (top level - avoids nested block quirks)
set "TOK_TMP=%TEMP%\arena_tok_%RANDOM%%RANDOM%.txt"
if defined HELPER (
    "%PY%" "%HELPER%" gentoken > "%TOK_TMP%"
) else (
    "%PY%" -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip(chr(61)))" > "%TOK_TMP%"
)
set "ARENA_TOKEN="
set /p "ARENA_TOKEN=" < "%TOK_TMP%"
del "%TOK_TMP%" 2>nul
if not defined ARENA_TOKEN (
    echo [ERROR] Failed to generate token
    set "HAD_ERROR=1"
    goto :final_check
)
> "%TOKEN_PATH%" <nul set /p="%ARENA_TOKEN%"
echo [OK] New token generated and saved to %TOKEN_PATH%
goto :token_done

:token_keep
echo [OK] Keeping existing token

:token_done
REM Re-read token from file (handles both new and existing)
set "ARENA_TOKEN="
set /p "ARENA_TOKEN=" < "%TOKEN_PATH%"

REM === 10. Generate start script ===
> "%BRIDGE_HOME%\start_ArenaUnifiedBridge.ps1" (
    echo # Auto-generated by install.bat - DO NOT EDIT
    echo $ErrorActionPreference = 'Stop'
    echo $BridgeDir = '%BRIDGE_HOME%'
    echo $AgentHome = '%ARENA_HOME%'
    echo $TokenFile = Join-Path $BridgeDir 'token.txt'
    echo $LogFile   = Join-Path $AgentHome 'logs\ArenaUnifiedBridge.log'
    echo if ^(-not ^(Test-Path $TokenFile^)^) { throw "Token file missing: $TokenFile" }
    echo $token = ^(Get-Content -Path $TokenFile -Raw^).Trim^(^)
    echo if ^($token.Length -lt 16^) { throw "Token in $TokenFile is too short" }
    echo $py = '%PYW%'
    echo $script = Join-Path $BridgeDir 'unified_bridge.py'
    echo $cmdArgs = @^('-u', $script, 'serve', '--root', $env:USERPROFILE, '--profile', '%ARENA_PROFILE%', '--token', $token, '--port', '%ARENA_PORT%'^)
    echo Set-Location $BridgeDir
    echo ^& $py @cmdArgs ^*^>^&1 ^| Tee-Object -FilePath $LogFile -Append
)
echo [OK] Wrote start_ArenaUnifiedBridge.ps1

REM === 11. Helper batches ===
> "%BRIDGE_HOME%\start.bat" (
    echo @echo off
    echo powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File "%BRIDGE_HOME%\start_ArenaUnifiedBridge.ps1"
)
> "%BRIDGE_HOME%\stop.bat" (
    echo @echo off
    echo schtasks /End /tn %ARENA_TASK_NAME% 2^>nul
    echo for /f "tokens=5" %%%%P in ^('netstat -ano ^^^| findstr ":%ARENA_PORT% "'^) do taskkill /F /PID %%%%P 2^>nul
    echo echo Bridge stopped
)
> "%BRIDGE_HOME%\status.bat" (
    echo @echo off
    echo curl -s http://127.0.0.1:%ARENA_PORT%/health
    echo echo.
)
echo [OK] Wrote start.bat / stop.bat / status.bat

REM === 12. Scheduled Task ===
if "%ARENA_NO_TASK%"=="1" (
    echo [SKIP] Scheduled Task creation skipped ^(ARENA_NO_TASK=1^)
    goto :skip_task
)

echo.
echo === Registering Scheduled Task: %ARENA_TASK_NAME% ===
schtasks /End /tn "%ARENA_TASK_NAME%" 2>nul >nul
schtasks /Delete /tn "%ARENA_TASK_NAME%" /F 2>nul >nul

schtasks /Create /tn "%ARENA_TASK_NAME%" /tr "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%BRIDGE_HOME%\start_ArenaUnifiedBridge.ps1\"" /sc onlogon /rl highest /f >nul 2>nul
if errorlevel 1 (
    schtasks /Create /tn "%ARENA_TASK_NAME%" /tr "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%BRIDGE_HOME%\start_ArenaUnifiedBridge.ps1\"" /sc onlogon /f >nul
)
echo [OK] Scheduled Task: %ARENA_TASK_NAME%

:skip_task

REM === 13. Restart bridge ===
if "%ARENA_NO_RESTART%"=="1" (
    echo [SKIP] Bridge restart skipped ^(ARENA_NO_RESTART=1^)
    goto :skip_restart
)

echo.
echo === Restarting bridge ===
if "%ARENA_NO_TASK%"=="0" schtasks /End /tn "%ARENA_TASK_NAME%" 2>nul >nul
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%ARENA_PORT% "') do taskkill /F /PID %%P >nul 2>nul
timeout /t 2 /nobreak >nul
if "%ARENA_NO_TASK%"=="0" (
    schtasks /Run /tn "%ARENA_TASK_NAME%" >nul
) else (
    start "" /B powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File "%BRIDGE_HOME%\start_ArenaUnifiedBridge.ps1"
)

echo Waiting for bridge to come up...
set /a "TRIES=0"
:health_loop
set /a "TRIES+=1"
timeout /t 1 /nobreak >nul
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:%ARENA_PORT%/health > "%TEMP%\arena_hc.txt" 2>nul
set /p "HC=" < "%TEMP%\arena_hc.txt"
del "%TEMP%\arena_hc.txt" 2>nul
if "%HC%"=="200" goto :hc_ok
if %TRIES% LSS 15 goto :health_loop
echo [WARN] Bridge not responding after 15s. Check log: %ARENA_HOME%\logs\ArenaUnifiedBridge.log
set "HAD_ERROR=1"
goto :show_done

:hc_ok
echo [OK] Bridge is healthy ^(HTTP 200^)

:skip_restart
:show_done
echo.
echo ============================================================
echo   INSTALLATION COMPLETE
echo ============================================================
echo   Bridge version : !FINAL_VERSION!  ^(was: !INSTALLED_VERSION!^)
echo   Task name      : %ARENA_TASK_NAME%
echo   Port           : %ARENA_PORT%
echo   Dashboard      : http://127.0.0.1:%ARENA_PORT%/gui
echo   Health         : http://127.0.0.1:%ARENA_PORT%/health
echo   Token file     : %TOKEN_PATH%
echo   Token          : !ARENA_TOKEN!
echo   Log            : %ARENA_HOME%\logs\ArenaUnifiedBridge.log
echo.
echo   Start  : %BRIDGE_HOME%\start.bat
echo   Stop   : %BRIDGE_HOME%\stop.bat
echo   Status : %BRIDGE_HOME%\status.bat
echo   Update : update.bat ^(preserves token^)
echo ============================================================
echo.
if not "%ARENA_NO_RESTART%"=="1" start "" "http://127.0.0.1:%ARENA_PORT%/gui"

:final_check
if "%HAD_ERROR%"=="1" (
    echo.
    echo [FAILED] Installation completed with errors. See above.
    pause
    exit /b 1
)

:end_ok
echo.
pause
endlocal
exit /b 0
