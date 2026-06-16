"""System service status diagnostics."""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from arena.service.windows import _sc_query_running, _windows_bridge_processes, _windows_scheduled_task_info
from arena.util import _subprocess_kwargs


def _windows_service_status(result: dict[str, Any]) -> None:
    nssm_running = False
    svc_name = os.environ.get("ARENA_SERVICE_NAME", "").strip() or "ArenaUnifiedBridge"
    exists, _raw, running = _sc_query_running(svc_name)
    if exists:
        if running:
            nssm_running = True
            nssm_detail = f'Service "{svc_name}" RUNNING (NSSM/SCM)'
        else:
            nssm_detail = f'Service "{svc_name}" present but not RUNNING'
    else:
        nssm_detail = f'Service "{svc_name}" not registered'
    result["windows_service"] = {"running": nssm_running, "detail": nssm_detail}

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


def _darwin_service_status(result: dict[str, Any]) -> None:
    launchd_active = False
    launchd_detail = ""
    try:
        out = subprocess.check_output(
            ["launchctl", "print", f"gui/{os.getuid()}/com.arena.bridge"],
            stderr=subprocess.DEVNULL,
            text=True,
            **_subprocess_kwargs(),
        )
        launchd_active = "running" in out.lower() or "active" in out.lower()
        launchd_detail = "com.arena.bridge loaded"
    except Exception:
        launchd_detail = "launchd service not found"
    result["launchd"] = {"active": launchd_active, "detail": launchd_detail}


def _linux_service_status(result: dict[str, Any]) -> None:
    sd_active = False
    sd_detail = ""
    try:
        out = subprocess.check_output(
            ["systemctl", "--user", "is-active", "arena-bridge"],
            stderr=subprocess.DEVNULL,
            **_subprocess_kwargs(),
        )
        status = out.decode("utf-8", errors="replace").strip()
        sd_active = status == "active"
        sd_detail = f"systemd user service: {status}"
    except Exception:
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


def _bridge_processes() -> list:
    try:
        if sys.platform == "win32":
            return _windows_bridge_processes()
        out = subprocess.check_output(["ps", "aux"], stderr=subprocess.DEVNULL, text=True, **_subprocess_kwargs())
        return [line.strip()[:200] for line in out.splitlines() if "unified_bridge" in line and "grep" not in line]
    except Exception:
        return []


def _tailscale_status() -> dict[str, Any]:
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
    return tailscale


def _sys_svc_sync() -> dict:
    """Synchronous helper to check service status."""
    result: dict[str, Any] = {"ok": True}
    if sys.platform == "win32":
        _windows_service_status(result)
    elif sys.platform == "darwin":
        _darwin_service_status(result)
    else:
        _linux_service_status(result)

    bridge_procs = _bridge_processes()
    result["bridge_processes"] = {"count": len(bridge_procs), "details": bridge_procs[:10]}
    result["tailscale"] = _tailscale_status()
    return result
