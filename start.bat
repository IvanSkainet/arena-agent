@echo off
title Arena Bridge — Start
echo Starting Arena Unified Bridge...
schtasks /Run /tn "ArenaUnifiedBridge" 2>nul
timeout /t 3 /nobreak >nul
curl -s http://127.0.0.1:8765/health 2>nul
echo.
pause
