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
from arena.service.windows import _ps_utf8_command, _sc_query_running, _windows_bridge_processes, _windows_scheduled_task_info




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

from arena.service.restart import spawn_respawn_helper as _restart_spawn_respawn_helper


def _spawn_respawn_helper(port: int) -> tuple[bool, str]:
    return _restart_spawn_respawn_helper(port, service_info_sync=_service_info_sync)
