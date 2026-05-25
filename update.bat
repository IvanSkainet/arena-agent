@echo off  
title Arena Local Agent — Windows Updater  
echo ==================================================  
echo === STARTING ARENA AGENT UPDATE ===  
echo ==================================================  
echo Stopping active services, copying files, and restarting...  
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_windows_service.ps1" -Update  
echo.  
echo Update completed successfully.  
echo.  
pause  