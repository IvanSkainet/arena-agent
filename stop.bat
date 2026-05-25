@echo off
title Arena Bridge — Stop
echo Stopping Arena Unified Bridge...
schtasks /End /tn "ArenaUnifiedBridge" 2>nul
timeout /t 2 /nobreak >nul
:: Also kill any process on port 8765
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8765 ^| findstr LISTEN') do (
    taskkill /PID %%a /F >nul 2>&1
)
echo Done. Bridge stopped.
