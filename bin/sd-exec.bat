@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "PY="
for %%X in (python.exe python3.exe py.exe) do (
    if not defined PY (
        for /f "delims=" %%I in ('where %%X 2^>nul') do (
            if not defined PY set "PY=%%I"
        )
    )
)
if not defined PY (
    echo [sd-exec] Python not found in PATH >&2
    exit /b 1
)
"%PY%" "%SCRIPT_DIR%\sd-exec" %*
exit /b %ERRORLEVEL%
