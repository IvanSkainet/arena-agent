"""Cross-platform bridge service autostart diagnosis/repair."""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any

from arena.util import _subprocess_kwargs

TASK = "ArenaUnifiedBridge"


def _run(cmd: list[str], timeout: int = 15) -> dict[str, Any]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **_subprocess_kwargs())
        return {"ok": p.returncode == 0, "exit": p.returncode, "stdout": (p.stdout or "")[:4000], "stderr": (p.stderr or "")[:2000]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _root() -> Path:
    return Path(os.environ.get("ARENA_AGENT_HOME") or Path(__file__).resolve().parents[2]).resolve()


def _windows_status() -> dict[str, Any]:
    q = _run(["schtasks", "/Query", "/TN", TASK, "/XML"], timeout=10)
    raw = q.get("stdout") or ""
    trigger = "unknown"
    if "LogonTrigger" in raw:
        trigger = "logon"
    elif "BootTrigger" in raw:
        trigger = "boot"
    elif "CalendarTrigger" in raw:
        trigger = "calendar"
    return {"ok": True, "platform": "windows", "registered": bool(q.get("ok")), "trigger": trigger,
            "healthy": bool(q.get("ok")) and trigger == "logon", "query": q,
            "expected": "per-user ONLOGON Scheduled Task (or NSSM service if installed)"}


def _linux_status() -> dict[str, Any]:
    enabled = _run(["systemctl", "--user", "is-enabled", "arena-bridge.service"], timeout=5)
    active = _run(["systemctl", "--user", "is-active", "arena-bridge.service"], timeout=5)
    return {"ok": True, "platform": "linux", "enabled": "enabled" in (enabled.get("stdout") or ""),
            "active": "active" in (active.get("stdout") or ""), "healthy": "enabled" in (enabled.get("stdout") or ""),
            "enabled_probe": enabled, "active_probe": active, "expected": "systemd --user enabled arena-bridge.service"}


def _darwin_status() -> dict[str, Any]:
    return {"ok": True, "platform": "darwin", "healthy": None, "expected": "launchd agent gui/$UID/com.arena.bridge", "note": "launchd repair is not implemented in this slice"}


def status() -> dict[str, Any]:
    sysname = platform.system().lower()
    if sysname == "windows":
        return _windows_status()
    if sysname == "linux":
        return _linux_status()
    if sysname == "darwin":
        return _darwin_status()
    return {"ok": False, "platform": sysname, "error": "unsupported platform"}


def repair() -> dict[str, Any]:
    sysname = platform.system().lower()
    if sysname == "windows":
        root = _root()
        vbs = root / "start_hidden.vbs"
        bat = root / "start_bridge.bat"
        if not vbs.exists() or not bat.exists():
            return {"ok": False, "error": "start_hidden.vbs/start_bridge.bat not found; rerun install.bat", "root": str(root)}
        _run(["schtasks", "/Delete", "/TN", TASK, "/F"], timeout=10)
        tr = f'wscript.exe "{vbs}"'
        cmd = ["schtasks", "/Create", "/TN", TASK, "/TR", tr, "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"]
        res = _run(cmd, timeout=20)
        fallback = None
        if not res.get("ok"):
            fallback = _run(["schtasks", "/Create", "/TN", TASK, "/TR", tr, "/SC", "ONLOGON", "/F"], timeout=20)
        _run(["schtasks", "/Run", "/TN", TASK], timeout=10)
        return {"ok": bool(res.get("ok") or (fallback and fallback.get("ok"))), "platform": "windows", "primary": res, "fallback": fallback, "status": _windows_status()}
    if sysname == "linux":
        res = _run(["systemctl", "--user", "enable", "--now", "arena-bridge.service"], timeout=20)
        return {"ok": bool(res.get("ok")), "platform": "linux", "result": res, "status": _linux_status()}
    if sysname == "darwin":
        return {"ok": False, "platform": "darwin", "error": "launchd repair is not implemented; rerun install.sh"}
    return {"ok": False, "platform": sysname, "error": "unsupported platform"}
