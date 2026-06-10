"""Service manager, process-status, and restart helpers.

Extracted from ``unified_bridge.py`` during the v3 modularization work.  These
functions are synchronous/stdlib-only and are re-exported by ``unified_bridge``
for compatibility with existing tests/imports.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from arena.constants import BRIDGE_DIR, TOKEN_FILE
from arena.util import _subprocess_kwargs

def _ps_utf8_command(script: str) -> list[str]:
    prefix = (
        "$OutputEncoding = [Console]::OutputEncoding = "
        "[System.Text.UTF8Encoding]::new($false); "
        "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
    )
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", prefix + script]

def _windows_scheduled_task_info(task_name: str) -> dict:
    info = {"exists": False, "running": False, "raw": ""}
    try:
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST", "/V"],
            capture_output=True, text=True, timeout=8, **_subprocess_kwargs(),
        )
        raw = (r.stdout or "") + (r.stderr or "")
        info["raw"] = raw[:1200]
        info["exists"] = (r.returncode == 0)
        low = raw.lower()
        # `schtasks` localizes labels and values, so combine English/Russian
        # words with the fact that /Run returned successfully elsewhere.
        info["running"] = ("running" in low) or ("выполня" in low)
    except Exception as e:
        info["error"] = str(e)[:200]
    return info

def _windows_bridge_processes() -> list[dict]:
    """Return matching Python bridge/helper processes with command lines."""
    if sys.platform != "win32":
        return []
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
        "Where-Object { $_.CommandLine -match 'arena|bridge|unified_bridge|local_bridge|mcp_ws|web_gateway|agentctl' } | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress -Depth 4"
    )
    try:
        r = subprocess.run(_ps_utf8_command(ps), capture_output=True, text=True, timeout=10, **_subprocess_kwargs())
        out = (r.stdout or "").strip()
        if not out:
            return []
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        procs = []
        for item in data:
            cmd = str(item.get("CommandLine") or "")
            role = "helper"
            if "unified_bridge.py" in cmd and " serve" in cmd:
                role = "main-bridge"
            elif "unified_bridge" in cmd:
                role = "bridge-related"
            procs.append({
                "pid": item.get("ProcessId"),
                "ppid": item.get("ParentProcessId"),
                "name": item.get("Name"),
                "role": role,
                "command_line": cmd[:1000],
            })
        return procs
    except Exception:
        return []

def _service_info_sync() -> dict:
    """Detect under what service manager (NSSM/Scheduled Task/systemd/launchd/none) we run."""
    result: dict[str, Any] = {"ok": True, "running_as": "unknown"}
    if sys.platform == "win32":
        svc_name = os.environ.get("ARENA_SERVICE_NAME", "").strip() or "ArenaUnifiedBridge"
        task_name = os.environ.get("ARENA_TASK_NAME", "").strip() or svc_name
        result["candidate_service"] = svc_name
        result["candidate_task"] = task_name
        exists, raw, running = _sc_query_running(svc_name)
        result["nssm_service"] = {"exists": exists, "running": running, "raw": raw[:800]}
        task = _windows_scheduled_task_info(task_name)
        result["scheduled_task"] = task
        procs = _windows_bridge_processes()
        result["bridge_processes"] = procs
        main_alive = any(p.get("role") == "main-bridge" and os.getpid() == p.get("pid") for p in procs) or bool(procs)
        if running:
            result["running_as"] = "nssm-service"
        elif task.get("exists") and main_alive:
            result["running_as"] = "scheduled-task"
        elif exists:
            result["running_as"] = "nssm-service-stopped"
            result["warning"] = "Windows service exists but is stopped; bridge may be running from Scheduled Task or manual start"
        elif task.get("exists"):
            result["running_as"] = "scheduled-task"
    elif sys.platform == "linux":
        try:
            r = subprocess.run(["systemctl", "--user", "is-active", "arena-bridge.service"],
                               capture_output=True, text=True, timeout=5,
                               **_subprocess_kwargs())
            if (r.stdout or "").strip() == "active":
                result["running_as"] = "systemd-user"
                result["systemd_user"] = {"active": True, "unit": "arena-bridge.service"}
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            r = subprocess.run(["launchctl", "print", "gui/0/com.arena.bridge"],
                               capture_output=True, text=True, timeout=5,
                               **_subprocess_kwargs())
            if r.returncode == 0:
                result["running_as"] = "launchd"
                result["launchd"] = {"loaded": True}
        except Exception:
            pass

    # PID info — always include
    result["pid"] = os.getpid()
    result["python"] = sys.executable
    return result

def _sc_query_running(svc_name: str) -> tuple[bool, str, bool]:
    """Run `sc query <name>` and return (exists, raw_output, running).
    Locale-agnostic: looks for the numeric state code `STATE` line containing
    "4" (RUNNING), in addition to any RUNNING substring.
    """
    try:
        r = subprocess.run(
            ["sc", "query", svc_name],
            capture_output=True, text=True, timeout=5,
            **_subprocess_kwargs(),
        )
    except Exception:
        return False, "", False
    out = (r.stdout or "") + (r.stderr or "")
    # `sc query` exits 1060 (ERROR_SERVICE_DOES_NOT_EXIST) -> no service
    if r.returncode == 1060 or "1060" in out:
        return False, out, False
    # Locale-agnostic checks
    # English: "STATE              : 4  RUNNING"
    # Russian: "Состояние          : 4  RUNNING"   (RUNNING is always English)
    # German:  "ZUSTAND            : 4  RUNNING"
    # Italian: "STATO              : 4  RUNNING"
    # etc. — "RUNNING" is constant; numeric state code `: 4 ` is constant.
    up = out.upper()
    running = ("RUNNING" in up) or (": 4 " in out) or (": 4\t" in out)
    # heuristic: presence of "_NAME" / numeric STATE row means service exists
    exists = (": 4 " in out) or (": 1 " in out) or (": 2 " in out) or (": 3 " in out) \
             or (": 5 " in out) or (": 6 " in out) or (": 7 " in out) \
             or ("RUNNING" in up) or ("STOPPED" in up) or ("PAUSED" in up) \
             or ("PENDING" in up)
    return exists, out, running

def _sys_svc_sync() -> dict:
    """Synchronous helper to check service status."""
    result: dict[str, Any] = {"ok": True}

    if sys.platform == "win32":
        # 1) NSSM / Windows Service Manager detection (locale-agnostic)
        nssm_running = False
        nssm_detail = ""
        svc_name = os.environ.get("ARENA_SERVICE_NAME", "").strip() or "ArenaUnifiedBridge"
        exists, raw, running = _sc_query_running(svc_name)
        if exists:
            if running:
                nssm_running = True
                nssm_detail = f'Service "{svc_name}" RUNNING (NSSM/SCM)'
            else:
                nssm_detail = f'Service "{svc_name}" present but not RUNNING'
        else:
            nssm_detail = f'Service "{svc_name}" not registered'
        result["windows_service"] = {"running": nssm_running, "detail": nssm_detail}

        # 2) Scheduled Task detection
        task_name = os.environ.get("ARENA_TASK_NAME", "").strip() or svc_name
        task_info = _windows_scheduled_task_info(task_name)
        result["scheduled_task"] = {
            "registered": task_info.get("exists", False),
            "running": task_info.get("running", False),
            "detail": f'Scheduled Task: "{task_name}"' if task_info.get("exists") else f'Scheduled Task "{task_name}" not registered',
            "raw": task_info.get("raw", "")[:500],
        }
        if nssm_running:
            result["manager"] = "windows-service"
        elif task_info.get("exists"):
            result["manager"] = "scheduled-task"
        else:
            result["manager"] = "manual-or-unknown"
        if exists and not running and task_info.get("exists"):
            result.setdefault("warnings", []).append("stale Windows service exists but Scheduled Task is the active install method")

    elif sys.platform == "darwin":
        # macOS launchd
        launchd_active = False
        launchd_detail = ""
        try:
            out = subprocess.check_output(
                ["launchctl", "print", f"gui/{os.getuid()}/com.arena.bridge"],
                stderr=subprocess.DEVNULL, text=True, **_subprocess_kwargs())
            launchd_active = "running" in out.lower() or "active" in out.lower()
            launchd_detail = "com.arena.bridge loaded"
        except Exception:
            launchd_detail = "launchd service not found"
        result["launchd"] = {"active": launchd_active, "detail": launchd_detail}

    else:
        # Linux — check systemd user service
        sd_active = False
        sd_detail = ""
        try:
            out = subprocess.check_output(
                ["systemctl", "--user", "is-active", "arena-bridge"],
                stderr=subprocess.DEVNULL, **_subprocess_kwargs())
            status = out.decode("utf-8", errors="replace").strip()
            sd_active = (status == "active")
            sd_detail = f"systemd user service: {status}"
        except Exception:
            # Check for cron as fallback
            try:
                out = subprocess.check_output(["crontab", "-l"], stderr=subprocess.DEVNULL, **_subprocess_kwargs())
                if b"unified_bridge" in out or b"arena" in out:
                    sd_active = True
                    sd_detail = "cron job found"
                else:
                    sd_detail = "No cron/systemd service"
            except Exception:
                sd_detail = "No service detected"
        result["systemd_user"] = {"active": sd_active, "detail": sd_detail}

    # Check running bridge processes
    bridge_procs = []
    try:
        if sys.platform == "win32":
            bridge_procs = _windows_bridge_processes()
        else:
            out = subprocess.check_output(
                ["ps", "aux"], stderr=subprocess.DEVNULL, text=True, **_subprocess_kwargs())
            for line in out.splitlines():
                if "unified_bridge" in line and "grep" not in line:
                    bridge_procs.append(line.strip()[:200])
    except Exception:
        pass
    result["bridge_processes"] = {"count": len(bridge_procs), "details": bridge_procs[:10]}

    # Check Tailscale status
    tailscale = {"installed": False, "connected": False, "detail": ""}
    try:
        out = subprocess.check_output(["tailscale", "status"], stderr=subprocess.DEVNULL, text=True, **_subprocess_kwargs())
        tailscale["installed"] = True
        tailscale["connected"] = bool(out.strip())
        tailscale["detail"] = out.strip()[:500]
    except FileNotFoundError:
        tailscale["detail"] = "tailscale not found"
    except Exception as e:
        tailscale["installed"] = True
        tailscale["detail"] = str(e)[:200]
    result["tailscale"] = tailscale

    return result

def _spawn_respawn_helper(port: int) -> tuple[bool, str]:
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
                service_managed = (_service_info_sync().get("running_as") == "nssm-service")
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
