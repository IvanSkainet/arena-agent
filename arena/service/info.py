"""Service manager detection helpers."""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from arena.service.windows import _sc_query_running, _windows_bridge_processes, _windows_scheduled_task_info
from arena.util import _subprocess_kwargs


def _is_android() -> bool:
    """True on Android, which lies about being plain Linux."""
    try:
        from arena import hostplatform
        return hostplatform.is_android()
    except Exception:
        # Detection must never take the service surface down with it.
        return False


def _termux_boot_info() -> dict[str, Any]:
    """What supervises the bridge on a phone, stated honestly.

    Three distinguishable states, because "unknown" helps nobody:

      * `termux-boot`  -- the hook exists AND the Termux:Boot app is
        installed, so a reboot really does bring the bridge back.
      * `termux-boot-hook-only` -- the script is there but the app is
        not, so nothing will run it. This is the state the bootstrap
        leaves behind when the operator has not installed Termux:Boot
        from F-Droid yet, and saying so is the difference between a
        working autostart and a believed one.
      * `manual` -- neither.
    """
    from pathlib import Path

    hook = Path(os.path.expanduser("~/.termux/boot/arena-bridge.sh"))
    hook_present = hook.is_file()
    app_present = Path("/data/data/com.termux.boot").exists()
    if not app_present:
        # The data dir is only readable by the app itself on some
        # devices; fall back to asking the package manager.
        try:
            probe = subprocess.run(
                ["pm", "path", "com.termux.boot"],
                capture_output=True, text=True, timeout=5,
                **_subprocess_kwargs(),
            )
            app_present = probe.returncode == 0 and "package:" in (probe.stdout or "")
        except Exception:
            app_present = False

    if hook_present and app_present:
        running_as = "termux-boot"
        note = "Termux:Boot will restart the bridge after a reboot."
    elif hook_present:
        running_as = "termux-boot-hook-only"
        note = ("The boot hook is installed but the Termux:Boot app is "
                "not. Install it from F-Droid; nothing runs the hook "
                "until then.")
    else:
        running_as = "manual"
        note = "No autostart configured. Re-run scripts/bootstrap_android.sh."

    return {
        "running_as": running_as,
        "termux_boot": {
            "hook": str(hook),
            "hook_present": hook_present,
            "app_installed": app_present,
            "note": note,
        },
    }


def _service_info_sync() -> dict:
    """Detect under what service manager (NSSM/Scheduled Task/systemd/launchd/none) we run."""
    result: dict[str, Any] = {"ok": True, "running_as": "unknown"}
    # Android first, deliberately. It reports sys.platform == "linux",
    # so a later `elif` never runs -- and on Windows CI the win32 branch
    # matched before it, sending simulated-phone tests into `sc query`.
    # This is a host-class question ("what machine is this?"), not a
    # sys.platform question, so it has to be asked before any of them.
    #
    # Termux has no systemd and no launchd. Its supervisor is
    # Termux:Boot: an executable in ~/.termux/boot that the app runs at
    # device start. Whether that exists is the honest answer to "what
    # will restart this bridge".
    if _is_android():
        result.update(_termux_boot_info())
    elif sys.platform == "win32":
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
