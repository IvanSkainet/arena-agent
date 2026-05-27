@echo off
REM Check Arena Unified Bridge status
echo.
echo  Arena Bridge Status
echo  ====================
curl -s http://127.0.0.1:8765/health 2>nul
if errorlevel 1 (
    echo  [DOWN] Bridge is not responding
) else (
    echo.
    echo  [UP] Bridge is running
)
echo.
pause
