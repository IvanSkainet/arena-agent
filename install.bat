@echo off
:: ============================================================
:: Arena Local Agent - Windows Installer Launcher v1.3.0
:: This batch file calls the PowerShell installer
:: ============================================================

title Arena Local Agent Installer

echo ============================================================
echo   Arena Local Agent - Installer v1.3.0
echo ============================================================
echo.

:: Check if running as administrator
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [INFO] Requesting administrator privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c %~dp0install.bat' -Verb RunAs"
    exit /b
)

:: Run the PowerShell installer
set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%scripts\install_windows_service.ps1"

:: Try scripts/ first, then same directory
if not exist "%PS_SCRIPT%" (
    set "PS_SCRIPT=%SCRIPT_DIR%install_windows_service.ps1"
)

if not exist "%PS_SCRIPT%" (
    echo [ERROR] Cannot find install_windows_service.ps1
    echo [ERROR] Make sure it's in the same folder or in scripts\ subfolder.
    echo.
    pause
    exit /b 1
)

echo [INFO] Launching PowerShell installer...
echo.

powershell -ExecutionPolicy Bypass -NoProfile -File "%PS_SCRIPT%"

if %errorLevel% neq 0 (
    echo.
    echo [ERROR] Installer exited with error code %errorLevel%
    echo.
)

pause
