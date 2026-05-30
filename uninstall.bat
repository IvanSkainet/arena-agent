@echo off
REM ============================================================
REM  Arena Unified Bridge — Uninstaller for Windows
REM  Removes service, scheduled task, and all bridge files.
REM  Run:  uninstall.bat
REM ============================================================
setlocal enabledelayedexpansion

echo.
echo  ========================================
echo   Arena Unified Bridge - Uninstaller
echo  ========================================
echo.

set "BRIDGE_DIR=%~dp0"
set "BRIDGE_DIR=%BRIDGE_DIR:~0,-1%"
set "PORT=8765"

REM --- Confirm ---
echo  This will completely remove Arena Unified Bridge:
echo    - Stop and remove NSSM service / Scheduled Task
echo    - Kill all bridge processes on port %PORT%
echo    - Delete the entire directory: %BRIDGE_DIR%
echo.
set /p "CONFIRM=Are you sure? This cannot be undone. [y/N]: "
if /i not "!CONFIRM!"=="y" (
    echo Cancelled.
    pause
    exit /b 0
)

echo.
echo [1/4] Stopping bridge processes...

REM --- Stop NSSM service if exists ---
where nssm >nul 2>&1
if not errorlevel 1 (
    nssm stop ArenaUnifiedBridge >nul 2>&1
    echo [OK] NSSM service stopped.
    nssm remove ArenaUnifiedBridge confirm >nul 2>&1
    echo [OK] NSSM service removed.
)

REM --- Stop Scheduled Task if exists ---
schtasks /query /tn "ArenaUnifiedBridge" >nul 2>&1
if not errorlevel 1 (
    schtasks /end /tn "ArenaUnifiedBridge" >nul 2>&1
    schtasks /delete /tn "ArenaUnifiedBridge" /f >nul 2>&1
    echo [OK] Scheduled task removed.
)

REM --- Kill processes on bridge port ---
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT% "') do (
    taskkill /F /PID %%P >nul 2>nul
)
echo [OK] Bridge processes killed.

echo.
echo [2/4] Stopping Tailscale Funnel (if active)...
where tailscale >nul 2>&1
if not errorlevel 1 (
    tailscale funnel off >nul 2>&1
    echo [OK] Tailscale funnel stopped.
) else (
    echo [SKIP] Tailscale not found.
)

echo.
echo [3/4] Removing bridge directory...
REM --- Remove the entire installation directory ---
cd /d "%TEMP%" 2>nul
rmdir /s /q "%BRIDGE_DIR%" 2>nul
if exist "%BRIDGE_DIR%" (
    echo [WARN] Could not fully delete %BRIDGE_DIR%
    echo        Some files may be locked. Delete manually after reboot.
    echo        Run: rmdir /s /q "%BRIDGE_DIR%"
) else (
    echo [OK] Directory removed.
)

echo.
echo [4/4] Removing old installation directories (if any)...
for %%d in ("%USERPROFILE%\.arena-local-bridge" "%USERPROFILE%\.arena-agent") do (
    if exist "%%d" (
        rmdir /s /q "%%d" 2>nul
        echo [OK] Removed %%d
    )
)

echo.
echo  ========================================
echo   Uninstallation Complete
echo  ========================================
echo.
echo   Arena Unified Bridge has been removed.
echo.
pause
