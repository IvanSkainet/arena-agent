@echo off
REM ============================================================
REM  Arena Unified Bridge — Stop Script (Windows)
REM  Stops bridge process, scheduled tasks, and all tunnels.
REM ============================================================
setlocal enabledelayedexpansion

set "PORT=8765"

echo.
echo  ========================================
echo   Stopping Arena Unified Bridge...
echo  ========================================
echo.

REM --- 1. Stop Windows service if exists ---
sc query ArenaUnifiedBridge >nul 2>&1
if not errorlevel 1 (
    sc stop ArenaUnifiedBridge >nul 2>&1
    where nssm >nul 2>&1
    if not errorlevel 1 nssm stop ArenaUnifiedBridge >nul 2>&1
    echo  [OK] Windows service stopped.
)

REM --- 2. Stop Scheduled Task if exists ---
schtasks /query /tn "ArenaUnifiedBridge" >nul 2>&1
if not errorlevel 1 (
    schtasks /end /tn "ArenaUnifiedBridge" >nul 2>&1
    echo  [OK] Scheduled task stopped.
)

REM --- 3. Kill python processes running unified_bridge ---
for /f "tokens=2" %%p in ('tasklist /fi "imagename eq pythonw.exe" /fi "commandline eq *unified_bridge*" /nh 2^>nul') do (
    taskkill /PID %%p /F >nul 2>&1
)
for /f "tokens=2" %%p in ('tasklist /fi "imagename eq python.exe" /fi "commandline eq *unified_bridge*" /nh 2^>nul') do (
    taskkill /PID %%p /F >nul 2>&1
)

REM --- 4. Kill processes strictly listening on bridge port ---
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr /I "LISTENING"') do (
    taskkill /F /PID %%P >nul 2>&1
)
echo  [OK] Bridge process stopped.

REM --- 5. Turn off Tailscale Funnel and Serve ---
where tailscale >nul 2>&1
if not errorlevel 1 (
    tailscale funnel off >nul 2>&1
    tailscale serve off >nul 2>&1
    echo  [OK] Tailscale funnel and serve turned off.
)

REM --- 6. Kill orphan tunnel processes ---
taskkill /F /IM cloudflared.exe >nul 2>&1
taskkill /F /IM ngrok.exe >nul 2>&1
taskkill /F /IM bore.exe >nul 2>&1

echo.
echo  [DONE] Arena Bridge and all tunnels fully stopped.
echo.
timeout /t 2 /nobreak >nul
