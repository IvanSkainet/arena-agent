@echo off
REM Start Arena Unified Bridge
cd /d "%~dp0"
python -u unified_bridge.py serve --root "%USERPROFILE%" --profile owner-shell --token-file token.txt --port 8765
pause
