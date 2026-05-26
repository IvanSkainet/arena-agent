@echo off
REM ============================================================
REM  Arena Local Agent - Update (Windows)
REM
REM  Preserves token. Only updates code files.
REM
REM  Env overrides:
REM    ARENA_HOME       default: %USERPROFILE%\arena-agent
REM    BRIDGE_HOME      default: %USERPROFILE%\arena-local-bridge
REM    ARENA_PORT       default: 8765
REM    ARENA_TASK_NAME  default: ArenaUnifiedBridge
REM
REM  CLI flags:
REM    --check-only / --dry-run  : show old/new version, don't change anything
REM    --no-restart              : update files but don't restart the bridge
REM ============================================================
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "ARENA_DRY_RUN=0"
set "ARENA_NO_RESTART=0"

:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--check-only" set "ARENA_DRY_RUN=1"
if /I "%~1"=="--dry-run"    set "ARENA_DRY_RUN=1"
if /I "%~1"=="--no-restart" set "ARENA_NO_RESTART=1"
shift
goto :parse_args
:args_done

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

for /f "tokens=* delims= " %%A in ("%USERPROFILE%") do set "USERPROFILE=%%A"

if not defined ARENA_HOME      set "ARENA_HOME=%USERPROFILE%\arena-agent"
if not defined BRIDGE_HOME     set "BRIDGE_HOME=%USERPROFILE%\arena-local-bridge"
if not defined ARENA_PORT      set "ARENA_PORT=8765"
if not defined ARENA_TASK_NAME set "ARENA_TASK_NAME=ArenaUnifiedBridge"

for /f "tokens=* delims= " %%A in ("%ARENA_HOME%")      do set "ARENA_HOME=%%A"
for /f "tokens=* delims= " %%A in ("%BRIDGE_HOME%")     do set "BRIDGE_HOME=%%A"
for /f "tokens=* delims= " %%A in ("%ARENA_PORT%")      do set "ARENA_PORT=%%A"
for /f "tokens=* delims= " %%A in ("%ARENA_TASK_NAME%") do set "ARENA_TASK_NAME=%%A"

echo ============================================================
echo   Arena Local Agent - Update
echo ============================================================
echo   Source     : %SCRIPT_DIR%
echo   Bridge home: %BRIDGE_HOME%
echo   Agent home : %ARENA_HOME%
echo   Port       : %ARENA_PORT%
echo   Task name  : %ARENA_TASK_NAME%
echo   Dry run    : %ARENA_DRY_RUN%
echo   No restart : %ARENA_NO_RESTART%
echo   Token      : PRESERVED
echo ============================================================
echo.

REM Find Python
set "PY="
for %%X in (python.exe python3.exe py.exe python.cmd python.bat) do (
    if not defined PY (
        for /f "delims=" %%I in ('where %%X 2^>nul') do (
            if not defined PY set "PY=%%I"
        )
    )
)
if not defined PY (
    echo [ERROR] Python not found
    pause
    exit /b 1
)
echo [OK] Python: %PY%

REM Locate helper
set "HELPER="
if exist "%SCRIPT_DIR%\_arena_helper.py"  set "HELPER=%SCRIPT_DIR%\_arena_helper.py"
if not defined HELPER if exist "%BRIDGE_HOME%\_arena_helper.py" set "HELPER=%BRIDGE_HOME%\_arena_helper.py"

REM Detect versions (use temp-file pattern, like install.bat)
set "OLD_VER=missing"
set "NEW_VER=n/a"
if defined HELPER (
    set "VTMP=%TEMP%\arena_upver_%RANDOM%%RANDOM%.txt"
    if exist "%BRIDGE_HOME%\unified_bridge.py" (
        "%PY%" "!HELPER!" version "%BRIDGE_HOME%\unified_bridge.py" > "!VTMP!" 2>nul
        set "OLD_VER="
        set /p "OLD_VER=" < "!VTMP!"
        if not defined OLD_VER set "OLD_VER=missing"
    )
    if exist "%SCRIPT_DIR%\unified_bridge.py" (
        "%PY%" "!HELPER!" version "%SCRIPT_DIR%\unified_bridge.py" > "!VTMP!" 2>nul
        set "NEW_VER="
        set /p "NEW_VER=" < "!VTMP!"
        if not defined NEW_VER set "NEW_VER=n/a"
    )
    del "!VTMP!" 2>nul
)
echo Old bridge version : !OLD_VER!
echo New bridge version : !NEW_VER!

if "%ARENA_DRY_RUN%"=="1" (
    echo.
    echo ============================================================
    echo   DRY RUN - no files were changed.
    echo ============================================================
    pause
    exit /b 0
)

REM === Copy new files ===
if exist "%SCRIPT_DIR%\unified_bridge.py" (
    copy /Y "%SCRIPT_DIR%\unified_bridge.py" "%BRIDGE_HOME%\unified_bridge.py" >nul
    echo [OK] Updated unified_bridge.py
)
if exist "%SCRIPT_DIR%\_arena_helper.py" (
    copy /Y "%SCRIPT_DIR%\_arena_helper.py" "%BRIDGE_HOME%\_arena_helper.py" >nul
    echo [OK] Updated _arena_helper.py
)
if exist "%SCRIPT_DIR%\dashboard\index.html" (
    copy /Y "%SCRIPT_DIR%\dashboard\index.html" "%ARENA_HOME%\dashboard\index.html" >nul
    copy /Y "%SCRIPT_DIR%\dashboard\index.html" "%BRIDGE_HOME%\index.html" >nul
    echo [OK] Updated dashboard/index.html
) else if exist "%SCRIPT_DIR%\index.html" (
    copy /Y "%SCRIPT_DIR%\index.html" "%ARENA_HOME%\dashboard\index.html" >nul
    copy /Y "%SCRIPT_DIR%\index.html" "%BRIDGE_HOME%\index.html" >nul
    echo [OK] Updated index.html
)
if exist "%SCRIPT_DIR%\bin\" (
    xcopy /Y /E /I /Q "%SCRIPT_DIR%\bin\*" "%ARENA_HOME%\bin\" >nul
    echo [OK] Updated bin/
)
if exist "%SCRIPT_DIR%\scripts\" (
    xcopy /Y /E /I /Q "%SCRIPT_DIR%\scripts\*" "%ARENA_HOME%\scripts\" >nul
    echo [OK] Updated scripts/
)

if "%ARENA_NO_RESTART%"=="1" (
    echo [SKIP] Restart skipped ^(--no-restart^)
    goto :show_done
)

REM === Restart bridge ===
echo.
echo === Restarting bridge ===
schtasks /End /tn "%ARENA_TASK_NAME%" 2>nul >nul
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%ARENA_PORT% "') do taskkill /F /PID %%P >nul 2>nul
timeout /t 2 /nobreak >nul
schtasks /Run /tn "%ARENA_TASK_NAME%" >nul

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
goto :show_done

:hc_ok
echo [OK] Bridge healthy

:show_done
echo.
echo ============================================================
echo   UPDATE COMPLETE: !OLD_VER! -^> !NEW_VER!
echo   Token preserved.
echo   Dashboard: http://127.0.0.1:%ARENA_PORT%/gui
echo ============================================================
echo.
pause
endlocal
exit /b 0
