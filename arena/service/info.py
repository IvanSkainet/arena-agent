"""Service manager detection helpers."""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from arena.service.windows import _sc_query_running, _windows_bridge_processes, _windows_scheduled_task_info
from arena.util import _subprocess_kwargs


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
            result_run = subprocess.run(
                ["systemctl", "--user", "is-active", "arena-bridge.service"],
                capture_output=True,
                text=True,
                timeout=5,
                **_subprocess_kwargs(),
            )
            if (result_run.stdout or "").strip() == "active":
                result["running_as"] = "systemd-user"
                result["systemd_user"] = {"active": True, "unit": "arena-bridge.service"}
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            result_run = subprocess.run(
                ["launchctl", "print", "gui/0/com.arena.bridge"],
                capture_output=True,
                text=True,
                timeout=5,
                **_subprocess_kwargs(),
            )
            if result_run.returncode == 0:
                result["running_as"] = "launchd"
                result["launchd"] = {"loaded": True}
        except Exception:
            pass

    result["pid"] = os.getpid()
    result["python"] = sys.executable
    return result
