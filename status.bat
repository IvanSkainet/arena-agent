@echo off
title Arena Bridge — Status
echo === Arena Unified Bridge Status ===
echo.
:: Check scheduled task
schtasks /query /tn "ArenaUnifiedBridge" /fo LIST 2>nul | findstr /i "Status TaskName"
echo.
:: Check health endpoint
echo Health check:
curl -s http://127.0.0.1:8765/health 2>nul
echo.
echo.
:: Check port
echo Port 8765:
netstat -ano | findstr :8765 | findstr LISTEN
if errorlevel 1 echo   Not listening
echo.
pause
