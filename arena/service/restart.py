"""Bridge restart/respawn helper."""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

from arena.constants import BRIDGE_DIR, TOKEN_FILE
from arena.util import _subprocess_kwargs


def spawn_respawn_helper(port: int, *, service_info_sync) -> tuple[bool, str]:
    """Spawn a detached helper script that waits ~2s, then re-launches the bridge.

    Drops a script file in TEMP and launches it via the platform's native
    detached-process mechanism, so the helper survives os._exit() of the parent.

    Returns (ok, method_used).
    """
    import subprocess as _sp
    import tempfile
    sys_name = platform.system()
    bridge_dir = BRIDGE_DIR
    bridge_py = str(BRIDGE_DIR / "unified_bridge.py")
    task_name = os.environ.get("ARENA_TASK_NAME", "ArenaUnifiedBridge")
    token_file = str(TOKEN_FILE)

    if sys_name == "Windows":
        # First try: is there an NSSM/SCM-managed service? If yes, just `net start` it after exit.
        svc_name = os.environ.get("ARENA_SERVICE_NAME", "").strip() or "ArenaUnifiedBridge"
        svc_exists = False
        try:
            r = _sp.run(["sc", "query", svc_name],
                        capture_output=True, text=True, timeout=5,
                        **_subprocess_kwargs())
            svc_exists = "SERVICE_NAME" in (r.stdout or "")
        except Exception:
            pass
        service_managed = False
        if svc_exists:
            try:
                # Only use the SCM/NSSM path when THIS bridge instance is
                # actually service-managed. A stale service can coexist with an
                # active Scheduled Task install and must not hijack restart.
                service_managed = (service_info_sync().get("running_as") == "nssm-service")
            except Exception:
                service_managed = False
        if service_managed:
            # NSSM/SCM-managed service is actually running. It should auto-restart
            # when this process exits; the helper only force-starts it if health
            # remains down. A stale stopped service must NOT take this branch.
            import tempfile
            sh_path = Path(tempfile.gettempdir()) / f"arena_nssm_kick_{os.getpid()}.bat"
            # Use a template + replace to avoid PowerShell-style quote/brace hell
            sh_template = r"""@echo off
timeout /t 8 /nobreak >nul
curl -s -o nul -w "%{http_code}" http://127.0.0.1:__PORT__/health > "%TEMP%\arena_kick_hc.txt" 2>nul
set /p HC=<"%TEMP%\arena_kick_hc.txt"
del "%TEMP%\arena_kick_hc.txt" >nul 2>&1
if not "%HC%"=="200" (
    sc start __SVC__ >nul 2>&1
)
(goto) 2>nul & del "%~f0"
"""
            sh = (sh_template
                  .replace("__PORT__", str(port))
                  .replace("__SVC__", svc_name)
                  .replace("\n", "\r\n"))
            try:
                sh_path.write_text(sh, encoding="ascii", newline="")
                DETACHED = 0x00000008
                CNPG = 0x00000200
                _sp.Popen(
                    ["cmd.exe", "/c", "start", "", "/B", str(sh_path)],
                    creationflags=DETACHED | CNPG,
                    stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                    close_fds=True, shell=False,
                )
                return True, f"NSSM auto-restart (service={svc_name})"
            except Exception as e:
                return False, f"NSSM spawn failed: {e}"

        # Fallback: Scheduled Task / direct python launch via .bat
        # Generate .bat with placeholders, then substitute (avoids escape hell)
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
        bat = (BAT_TEMPLATE
               .replace("__TASK__", task_name)
               .replace("__PID__", str(os.getpid()))
               .replace("__PORT__", str(port))
               .replace("__BRIDGE__", bridge_py)
               .replace("__TOKEN_FILE__", token_file))
        bat_path = Path(tempfile.gettempdir()) / f"arena_respawn_{os.getpid()}.bat"
        try:
            # Use CRLF line endings so cmd parses it cleanly
            bat = bat.replace("\n", "\r\n")
            bat_path.write_text(bat, encoding="ascii", newline="")
            DETACHED = 0x00000008
            CNPG = 0x00000200
            _sp.Popen(
                ["cmd.exe", "/c", "start", "", "/B", str(bat_path)],
                creationflags=DETACHED | CNPG,
                stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                close_fds=True,
                shell=False,
            )
            return True, f"detached .bat (task={task_name}, file={bat_path.name})"
        except Exception as e:
            return False, f"spawn failed: {e}"

    elif sys_name == "Linux":
        # Prefer a transient systemd user unit. A plain child process can be
        # killed together with arena-bridge.service's cgroup when the bridge
        # exits, which made /v1/restart unreliable on systemd desktops.
        SYSTEMD_RUN_TEMPLATE = r"""
sleep 2
systemctl --user restart arena-bridge.service >/dev/null 2>&1 || true
for i in $(seq 1 20); do
    if curl -fsS http://127.0.0.1:__PORT__/health >/dev/null 2>&1; then
        exit 0
    fi
    sleep 1
done
TOK=""
if [ -f "__TOKEN_FILE__" ]; then
    TOK="$(cat '__TOKEN_FILE__' | tr -d '\n ' )"
fi
nohup python3 -u "__BRIDGE__" serve --root "$HOME" --profile owner-shell ${TOK:+--token "$TOK"} --port __PORT__ >/dev/null 2>&1 &
"""
        systemd_script = (SYSTEMD_RUN_TEMPLATE
                          .replace("__PORT__", str(port))
                          .replace("__BRIDGE__", bridge_py)
                          .replace("__TOKEN_FILE__", token_file))
        try:
            if shutil.which("systemd-run") and shutil.which("systemctl"):
                unit = f"arena-bridge-restart-{os.getpid()}"
                r = _sp.run(
                    ["systemd-run", "--user", "--unit", unit, "--collect", "bash", "-lc", systemd_script],
                    capture_output=True, text=True, timeout=5,
                    **_subprocess_kwargs(),
                )
                if r.returncode == 0:
                    return True, f"systemd-run transient unit ({unit})"
        except Exception:
            pass

        # Fallback for non-systemd Linux: detached shell script. This may be
        # killed by systemd cgroup cleanup when running under systemd, hence it
        # is intentionally second choice.
        SH_TEMPLATE = r"""#!/usr/bin/env bash
sleep 2
if command -v systemctl >/dev/null 2>&1 && systemctl --user list-unit-files arena-bridge.service >/dev/null 2>&1; then
    systemctl --user restart arena-bridge.service
fi
for i in $(seq 1 12); do
    if curl -fsS http://127.0.0.1:__PORT__/health >/dev/null 2>&1; then
        rm -f "$0"; exit 0
    fi
    sleep 1
done
TOK=""
[[ -f "__TOKEN_FILE__" ]] && TOK="$(cat '__TOKEN_FILE__' | tr -d '\n ')"
nohup python3 -u "__BRIDGE__" serve --root "$HOME" --profile owner-shell ${TOK:+--token "$TOK"} --port __PORT__ >/dev/null 2>&1 &
disown
rm -f "$0"
"""
        sh = (SH_TEMPLATE
              .replace("__PORT__", str(port))
              .replace("__BRIDGE__", bridge_py)
              .replace("__TOKEN_FILE__", token_file))
        sh_path = Path(tempfile.gettempdir()) / f"arena_respawn_{os.getpid()}.sh"
        try:
            sh_path.write_text(sh, encoding="utf-8")
            sh_path.chmod(0o755)
            _sp.Popen(["bash", str(sh_path)], start_new_session=True,
                      stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                      close_fds=True)
            return True, f"detached .sh fallback (file={sh_path.name})"
        except Exception as e:
            return False, f"spawn failed: {e}"

    elif sys_name == "Darwin":
        SH_TEMPLATE = r"""#!/usr/bin/env bash
sleep 2
if launchctl print "gui/$UID/com.arena.bridge" >/dev/null 2>&1; then
    launchctl kickstart -k "gui/$UID/com.arena.bridge"
fi
for i in $(seq 1 12); do
    if curl -fsS http://127.0.0.1:__PORT__/health >/dev/null 2>&1; then
        rm -f "$0"; exit 0
    fi
    sleep 1
done
TOK=""
[[ -f "__TOKEN_FILE__" ]] && TOK="$(cat '__TOKEN_FILE__' | tr -d '
 ')"
nohup python3 -u "__BRIDGE__" serve --root "$HOME" --profile owner-shell ${TOK:+--token "$TOK"} --port __PORT__ >/dev/null 2>&1 &
disown
rm -f "$0"
"""
        sh = (SH_TEMPLATE
              .replace("__PORT__", str(port))
              .replace("__BRIDGE__", bridge_py)
              .replace("__TOKEN_FILE__", token_file))
        sh_path = Path(tempfile.gettempdir()) / f"arena_respawn_{os.getpid()}.sh"
        try:
            sh_path.write_text(sh, encoding="utf-8")
            sh_path.chmod(0o755)
            _sp.Popen(["bash", str(sh_path)], start_new_session=True,
                      stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                      close_fds=True)
            return True, f"detached .sh (file={sh_path.name})"
        except Exception as e:
            return False, f"spawn failed: {e}"

    return False, f"unsupported platform: {sys_name}"
