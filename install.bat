@echo off  
title Arena Local Agent — Windows Installer  
echo ==================================================  
echo === STARTING ARENA AGENT INSTALLATION ===  
echo ==================================================  
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_windows_service.ps1"  
echo.  
echo Installation completed successfully.  
echo To open the dashboard, visit: http://127.0.0.1:8765/gui  
echo.  
pause  