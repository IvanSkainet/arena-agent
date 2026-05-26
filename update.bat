@echo off
:: ============================================================
:: Arena Local Agent - Quick Update Script v1.3.0
:: Stops bridge, copies new files, restarts bridge
:: ============================================================

title Arena Local Agent - Update

echo ============================================================
echo   Arena Local Agent - Quick Update v1.3.0
echo ============================================================
echo.

set "BRIDGE_DIR=%USERPROFILE%\arena-local-bridge"
set "AGENT_DIR=%USERPROFILE%\arena-agent"
set "SCRIPT_DIR=%~dp0"

:: Step 1: Stop the bridge
echo [1/4] Stopping bridge...
schtasks /End /tn ArenaUnifiedBridge >nul 2>&1
timeout /t 3 /nobreak >nul

:: Step 2: Copy new files
echo [2/4] Updating files...

:: Copy unified_bridge.py
if exist "%SCRIPT_DIR%unified_bridge.py" (
    copy /y "%SCRIPT_DIR%unified_bridge.py" "%BRIDGE_DIR%\unified_bridge.py" >nul 2>&1
    echo   [OK] unified_bridge.py updated
) else if exist "%SCRIPT_DIR%arena-local-bridge\unified_bridge.py" (
    copy /y "%SCRIPT_DIR%arena-local-bridge\unified_bridge.py" "%BRIDGE_DIR%\unified_bridge.py" >nul 2>&1
    echo   [OK] unified_bridge.py updated
) else (
    echo   [SKIP] unified_bridge.py not found in source
)

:: Copy installer
if exist "%SCRIPT_DIR%install_windows_service.ps1" (
    if not exist "%AGENT_DIR%\scripts" mkdir "%AGENT_DIR%\scripts"
    copy /y "%SCRIPT_DIR%install_windows_service.ps1" "%AGENT_DIR%\scripts\install_windows_service.ps1" >nul 2>&1
    echo   [OK] install_windows_service.ps1 updated
)

:: Copy start script
if exist "%SCRIPT_DIR%start_ArenaUnifiedBridge.ps1" (
    copy /y "%SCRIPT_DIR%start_ArenaUnifiedBridge.ps1" "%BRIDGE_DIR%\start_ArenaUnifiedBridge.ps1" >nul 2>&1
    echo   [OK] start_ArenaUnifiedBridge.ps1 updated
)

:: Copy regenerate_token.bat
if exist "%SCRIPT_DIR%regenerate_token.bat" (
    copy /y "%SCRIPT_DIR%regenerate_token.bat" "%BRIDGE_DIR%\regenerate_token.bat" >nul 2>&1
    echo   [OK] regenerate_token.bat updated
)

:: Step 3: Regenerate token
echo [3/4] Regenerating token...

:: Find Python
set "PYTHON="
for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) do (
    if exist %%p set "PYTHON=%%~p"
)
if not defined PYTHON (
    where python >nul 2>&1
    if errorlevel 1 (
        echo   [ERROR] Python not found. Token not regenerated.
        goto :start_bridge
    )
    set "PYTHON=python"
)

for /f "delims=" %%t in ('"%PYTHON%" -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip(\"=\"))"') do set "NEW_TOKEN=%%t"
if defined NEW_TOKEN (
    echo %NEW_TOKEN%> "%BRIDGE_DIR%\token.txt"
    echo   [OK] New token generated
) else (
    echo   [WARN] Token generation failed, keeping existing
)

:: Step 4: Restart bridge
:start_bridge
echo [4/4] Restarting bridge...
schtasks /Run /tn ArenaUnifiedBridge >nul 2>&1
timeout /t 3 /nobreak >nul

:: Health check
curl -s http://127.0.0.1:8765/health 2>nul
echo.

echo.
echo ============================================================
echo   Update complete!
echo   Dashboard: http://127.0.0.1:8765/gui
echo ============================================================
echo.
pause
