"""Linux/CachyOS flight check for the ship map."""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
from typing import Any

from arena.admin.tailscale import sys_funnel_status
from arena.mobile import preflight as mobile_preflight
from arena.util import _subprocess_kwargs
from arena.workbench import runtime_compat, runtimes


def _run(cmd: list[str], timeout: int = 8) -> dict[str, Any]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **_subprocess_kwargs())
        return {"ok": p.returncode == 0, "exit": p.returncode, "stdout": (p.stdout or "")[:4000], "stderr": (p.stderr or "")[:2000]}
    except FileNotFoundError:
        return {"ok": False, "error": f"command not found: {cmd[0]}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _version_cmd(name: str, args: list[str] | None = None) -> dict[str, Any]:
    exe = shutil.which(name)
    if not exe:
        return {"available": False, "path": None}
    res = _run([exe, *(args or ["--version"])], timeout=5)
    text = (res.get("stdout") or res.get("stderr") or "").strip().splitlines()
    return {"available": True, "path": exe, "version": text[0] if text else None, "probe": res}


def _service_status() -> dict[str, Any]:
    return {
        "systemctl_user": _run(["systemctl", "--user", "is-active", "arena-bridge"], timeout=5),
        "systemctl_user_status": _run(["systemctl", "--user", "status", "arena-bridge", "--no-pager"], timeout=8),
    }


def _desktop_status() -> dict[str, Any]:
    env = {k: os.environ.get(k, "") for k in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY", "KDE_FULL_SESSION")}
    return {
        "env": env,
        "kwin_wayland": _version_cmd("kwin_wayland", ["--version"]),
        "plasmashell": _version_cmd("plasmashell", ["--version"]),
        "xdg_session": _run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Sessions", "--value"], timeout=5) if shutil.which("loginctl") else {"ok": False, "error": "loginctl not found"},
    }


def _browser_status() -> dict[str, Any]:
    candidates = ["google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave", "firefox"]
    found = {name: shutil.which(name) for name in candidates if shutil.which(name)}
    return {
        "binaries": found,
        "browseract": _version_cmd("browser-act", ["--version"]),
        "note": "CDP from a user service may need a real desktop/Wayland/X11 session and an active browser profile.",
    }


def _tailscale_status() -> dict[str, Any]:
    return {
        "cli": _version_cmd("tailscale", ["version"]),
        "status": _run(["tailscale", "status"], timeout=8),
        "funnel": sys_funnel_status(subprocess_kwargs=_subprocess_kwargs),
    }


def status() -> dict[str, Any]:
    rt = runtimes.probe()
    compat = runtime_compat.build(rt)
    mobile = mobile_preflight.preflight()
    checks = [
        {"name": "linux.platform", "ok": platform.system().lower() == "linux", "severity": "fail", "detail": platform.platform()},
        {"name": "systemd_run.available", "ok": bool(shutil.which("systemd-run")), "severity": "fail", "detail": shutil.which("systemd-run") or "missing"},
        {"name": "systemd_user_service.active", "ok": "active" in (_run(["systemctl", "--user", "is-active", "arena-bridge"], timeout=5).get("stdout") or ""), "severity": "warn", "detail": "arena-bridge.service"},
        {"name": "tailscale.cli", "ok": bool(shutil.which("tailscale")), "severity": "warn", "detail": shutil.which("tailscale") or "missing"},
        {"name": "adb.mobile_ready", "ok": bool(mobile.get("ready")), "severity": "warn", "detail": str(mobile.get("selected_serial") or mobile.get("mode"))},
    ]
    warnings = [c for c in checks if not c["ok"] and c["severity"] == "warn"]
    failed = [c for c in checks if not c["ok"] and c["severity"] == "fail"]
    return {
        "ok": not failed,
        "ready": not failed and not warnings,
        "mode": "blocked" if failed else ("degraded" if warnings else "nominal"),
        "host": {"hostname": socket.gethostname(), "platform": platform.platform(), "python": platform.python_version()},
        "service": _service_status(),
        "desktop": _desktop_status(),
        "tailscale": _tailscale_status(),
        "mobile": mobile,
        "browser": _browser_status(),
        "runtimes": rt,
        "runtime_compat": compat,
        "checks": checks,
        "warnings": warnings,
        "failed": failed,
        "next_actions": [
            "Run a fenced Workbench smoke with code.run under systemd posture.",
            "Use mobile.observe before any Android input actions; respect lock/PIN boundary.",
            "If browser/CDP work is needed, run a headed browser proof in the active KDE/Wayland user session.",
        ],
    }
