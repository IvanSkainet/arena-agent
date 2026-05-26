@echo off
:: Arena Local Bridge - Token Regeneration Script v1.3.0
:: Regenerates token and restarts bridge automatically

setlocal enabledelayedexpansion

set "BRIDGE_DIR=%USERPROFILE%\arena-local-bridge"
set "TOKEN_FILE=%BRIDGE_DIR%\token.txt"
set "PYTHON="

:: Find Python (check all common locations)
for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
) do (
    if exist %%p set "PYTHON=%%~p"
)
if not defined PYTHON (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found. Please install Python 3.10+
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

echo ============================================================
echo   Arena Local Bridge - Token Regeneration v1.3.0
echo ============================================================
echo.

:: Step 1: Stop the bridge
echo [1/3] Stopping bridge...
schtasks /End /tn ArenaUnifiedBridge >nul 2>&1
timeout /t 2 /nobreak >nul

:: Step 2: Generate new token
echo [2/3] Generating new token...
for /f "delims=" %%t in ('"%PYTHON%" -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip(\"=\"))"') do set "NEW_TOKEN=%%t"

if not defined NEW_TOKEN (
    echo [ERROR] Failed to generate token
    pause
    exit /b 1
)

:: Save token
if not exist "%BRIDGE_DIR%" mkdir "%BRIDGE_DIR%"
echo %NEW_TOKEN%> "%TOKEN_FILE%"
echo   Token saved to %TOKEN_FILE%

:: Step 3: Restart the bridge
echo [3/3] Restarting bridge...
schtasks /Run /tn ArenaUnifiedBridge >nul 2>&1
timeout /t 3 /nobreak >nul

:: Health check
echo.
echo [Health Check]
curl -s http://127.0.0.1:8765/health 2>nul
echo.

echo.
echo ============================================================
echo   Token regenerated successfully!
echo   New token: %NEW_TOKEN%
echo ============================================================
echo.
echo Use this token for API calls:
echo   Authorization: Bearer %NEW_TOKEN%
echo.
echo Dashboard: http://127.0.0.1:8765/gui
echo.
pause
