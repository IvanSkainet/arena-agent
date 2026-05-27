@echo off
REM ============================================================
REM  Arena Unified Bridge - Update (Windows)
REM  Preserves token. Updates code. Restarts service.
REM ============================================================
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "PORT=8765"
set "TOKEN_FILE=%SCRIPT_DIR%\token.txt"

echo ============================================================
echo   Arena Bridge - Update
echo ============================================================

REM Find Python
set "PY="
for %%X in (python.exe python3.exe py.exe) do (
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

REM Pull latest from git
echo [INFO] Pulling latest from git...
cd /d "%SCRIPT_DIR%"
git pull --ff-only >nul 2>&1 || echo [WARN] git pull failed, using local files

REM Restart bridge
echo [INFO] Restarting bridge...
where nssm >nul 2>&1
if not errorlevel 1 (
    nssm restart ArenaUnifiedBridge >nul 2>&1
    echo [OK] NSSM service restarted
) else (
    schtasks /End /tn "ArenaUnifiedBridge" >nul 2>&1
    for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT% "') do taskkill /F /PID %%P >nul 2>nul
    timeout /t 2 /nobreak >nul
    schtasks /Run /tn "ArenaUnifiedBridge" >nul 2>&1
    echo [OK] Scheduled task restarted
)

echo Waiting for bridge...
set /a "TRIES=0"
:health_loop
set /a "TRIES+=1"
timeout /t 1 /nobreak >nul
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:%PORT%/health > "%TEMP%\arena_hc.txt" 2>nul
set /p "HC=" < "%TEMP%\arena_hc.txt"
del "%TEMP%\arena_hc.txt" 2>nul
if "%HC%"=="200" goto :hc_ok
if %TRIES% LSS 15 goto :health_loop
echo [WARN] Bridge not responding after 15s.
goto :done

:hc_ok
echo [OK] Bridge healthy

:done
echo.
echo ============================================================
echo   UPDATE COMPLETE
echo   Token preserved.
echo   Dashboard: http://127.0.0.1:%PORT%/gui
echo ============================================================
pause
endlocal
