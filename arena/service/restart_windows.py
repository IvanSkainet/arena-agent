"""Windows restart/respawn helper implementation."""
from __future__ import annotations

import os
import subprocess as sp

from arena.service.restart_common import RestartContext, render_template, temp_script_path, write_script
from arena.util import _subprocess_kwargs


NSSM_KICK_TEMPLATE = r"""@echo off
timeout /t 8 /nobreak >nul
curl -s -o nul -w "%{http_code}" http://127.0.0.1:__PORT__/health > "%TEMP%\arena_kick_hc.txt" 2>nul
set /p HC=<"%TEMP%\arena_kick_hc.txt"
del "%TEMP%\arena_kick_hc.txt" >nul 2>&1
if not "%HC%"=="200" (
    sc start __SVC__ >nul 2>&1
)
(goto) 2>nul & del "%~f0"
"""

BAT_TEMPLATE = r"""@echo off
timeout /t 2 /nobreak >nul
REM Ensure the previous bridge process is gone. schtasks /End can stop only
REM the wscript/task wrapper and leave python.exe orphaned.
taskkill /PID __PID__ /F >nul 2>nul
timeout /t 1 /nobreak >nul
REM Try Scheduled Task first
set "ARENA_TASK=__TASK__"
schtasks /Query /TN "%ARENA_TASK%" >nul 2>&1
if not errorlevel 1 (
    schtasks /End /TN "%ARENA_TASK%" >nul 2>&1
    timeout /t 1 /nobreak >nul
    schtasks /Run /TN "%ARENA_TASK%" >nul 2>&1
)
REM Poll /health for ~12 sec
set TRIES=0
:poll
set /a TRIES+=1
timeout /t 1 /nobreak >nul
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:__PORT__/health > "%TEMP%\arena_hc_chk.txt" 2>nul
set /p HC=<"%TEMP%\arena_hc_chk.txt"
del "%TEMP%\arena_hc_chk.txt" >nul 2>&1
if "%HC%"=="200" goto :cleanup
if %TRIES% LSS 12 goto :poll
REM Last-resort: launch pythonw directly with token from file
set "TOK="
if exist "__TOKEN_FILE__" set /p TOK=<"__TOKEN_FILE__"
set "PYW="
for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%P"
if not defined PYW for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined PYW set "PYW=%%P"
if defined PYW (
    if defined TOK (
        start "" /B "%PYW%" -u "__BRIDGE__" serve --root "%USERPROFILE%" --profile owner-shell --token "%TOK%" --port __PORT__
    ) else (
        start "" /B "%PYW%" -u "__BRIDGE__" serve --root "%USERPROFILE%" --profile owner-shell --port __PORT__
    )
)
:cleanup
(goto) 2>nul & del "%~f0"
"""


def _popen_cmd_bat(path) -> None:
    detached = 0x00000008
    cnpg = 0x00000200
    sp.Popen(
        ["cmd.exe", "/c", "start", "", "/B", str(path)],
        creationflags=detached | cnpg,
        stdin=sp.DEVNULL,
        stdout=sp.DEVNULL,
        stderr=sp.DEVNULL,
        close_fds=True,
        shell=False,
    )


def _service_exists(service_name: str) -> bool:
    try:
        result = sp.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
            timeout=5,
            **_subprocess_kwargs(),
        )
        return "SERVICE_NAME" in (result.stdout or "")
    except Exception:
        return False


def _is_current_instance_service_managed(service_name: str, service_info_sync) -> bool:
    if not _service_exists(service_name):
        return False
    try:
        return service_info_sync().get("running_as") == "nssm-service"
    except Exception:
        return False


def spawn_windows_respawn_helper(ctx: RestartContext, *, service_info_sync) -> tuple[bool, str]:
    service_name = os.environ.get("ARENA_SERVICE_NAME", "").strip() or "ArenaUnifiedBridge"
    if _is_current_instance_service_managed(service_name, service_info_sync):
        path = temp_script_path("arena_nssm_kick", ".bat", ctx.pid)
        script = render_template(NSSM_KICK_TEMPLATE, ctx).replace("__SVC__", service_name).replace("\n", "\r\n")
        try:
            write_script(path, script, encoding="ascii")
            _popen_cmd_bat(path)
            return True, f"NSSM auto-restart (service={service_name})"
        except Exception as e:
            return False, f"NSSM spawn failed: {e}"

    path = temp_script_path("arena_respawn", ".bat", ctx.pid)
    script = render_template(BAT_TEMPLATE, ctx).replace("\n", "\r\n")
    try:
        write_script(path, script, encoding="ascii")
        _popen_cmd_bat(path)
        return True, f"detached .bat (task={ctx.task_name}, file={path.name})"
    except Exception as e:
        return False, f"spawn failed: {e}"
