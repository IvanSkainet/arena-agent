@echo off
REM Arena Agent CLI wrapper (Windows)
REM Finds Python and runs agentctl.py
setlocal enabledelayedexpansion

set "AGENT_HOME=%ARENA_AGENT_HOME%"
if "%AGENT_HOME%"=="" set "AGENT_HOME=%USERPROFILE%\arena-bridge"

for %%p in (
  "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "C:\Python314\python.exe"
  "C:\Python313\python.exe"
  "C:\Python312\python.exe"
  "python"
) do (
  if exist %%p (
    "%%~p" "%AGENT_HOME%\bin\agentctl" %*
    exit /b !errorlevel!
  )
)
echo ERROR: Python not found
exit /b 1
