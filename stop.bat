@echo off
REM Stop Arena Unified Bridge
where nssm >nul 2>&1
if not errorlevel 1 (
    nssm stop ArenaUnifiedBridge
) else (
    for /f "tokens=2" %%p in ('tasklist /fi "imagename eq pythonw.exe" /fi "commandline eq *unified_bridge*" /nh 2^>nul') do (
        taskkill /pid %%p /f >nul 2>&1
    )
)
echo Bridge stopped.
timeout /t 2 /nobreak >nul
