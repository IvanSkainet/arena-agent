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


def write_windows_launchers(root: Path, *, port: int = 8765,
                            profile: str = "owner-shell") -> dict[str, Any]:
    """Create `start_bridge.bat` and `start_hidden.vbs` if they are missing.

    Only `install.bat` used to write these, so an install made by
    unzipping a release -- the documented quick start -- had no way to
    relaunch the bridge after `update/restart`. The PC went down that
    way twice (see v4.169.21), and `repair()` could only answer
    "rerun install.bat", which is not something a remote agent can do.

    They are two short files and everything they need is knowable here,
    so there is no reason for their absence to be terminal. Existing
    files are never overwritten: a hand-tuned launcher on someone's
    machine outranks this default.
    """
    created: list[str] = []
    bat = root / "start_bridge.bat"
    vbs = root / "start_hidden.vbs"
    token_file = os.environ.get("ARENA_TOKEN_FILE") or str(root / "token.txt")
    python = os.environ.get("ARENA_PYTHON") or "python"

    if not bat.exists():
        bat.write_bytes((
            "\r\n".join([
                "@echo off",
                f'cd /d "{root}"',
                f"set ARENA_AGENT_HOME={root}",
                f"set ARENA_TOKEN_FILE={token_file}",
                f'{python} -u unified_bridge.py serve --profile {profile} '
                f"--port {port}",
            ]) + "\r\n").encode("utf-8"))
        created.append(bat.name)

    if not vbs.exists():
        vbs.write_bytes((
            "\r\n".join([
                'Set WshShell = CreateObject("WScript.Shell")',
                f'WshShell.Run """{bat}""", 0, False',
            ]) + "\r\n").encode("utf-8"))
        created.append(vbs.name)

    return {"ok": bat.exists() and vbs.exists(), "created": created,
            "start_bridge_bat": str(bat), "start_hidden_vbs": str(vbs)}


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
        # v4.169.21: write them rather than refusing. "Rerun install.bat"
        # is not an instruction a remote agent -- or an operator whose
        # bridge is already down -- can act on.
        written = write_windows_launchers(root)
        if not written["ok"]:
            return {"ok": False, "error": "could not create start_hidden.vbs / "
                                          "start_bridge.bat",
                    "root": str(root), "write": written}
        _run(["schtasks", "/Delete", "/TN", TASK, "/F"], timeout=10)
        tr = f'wscript.exe "{vbs}"'
        cmd = ["schtasks", "/Create", "/TN", TASK, "/TR", tr, "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"]
        res = _run(cmd, timeout=20)
        fallback = None
        if not res.get("ok"):
            fallback = _run(["schtasks", "/Create", "/TN", TASK, "/TR", tr, "/SC", "ONLOGON", "/F"], timeout=20)
        _run(["schtasks", "/Run", "/TN", TASK], timeout=10)
        return {"ok": bool(res.get("ok") or (fallback and fallback.get("ok"))),
                "platform": "windows", "launchers": written, "primary": res,
                "fallback": fallback, "status": _windows_status()}
    if sysname == "linux":
        res = _run(["systemctl", "--user", "enable", "--now", "arena-bridge.service"], timeout=20)
        return {"ok": bool(res.get("ok")), "platform": "linux", "result": res, "status": _linux_status()}
    if sysname == "darwin":
        return {"ok": False, "platform": "darwin", "error": "launchd repair is not implemented; rerun install.sh"}
    return {"ok": False, "platform": sysname, "error": "unsupported platform"}
