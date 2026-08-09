"""Cross-platform bridge service autostart diagnosis/repair."""
from __future__ import annotations

import os
import platform
import subprocess
import sys
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


def _python_for_scheduler() -> str:
    """An interpreter the Task Scheduler can actually find.

    The launcher used to emit a bare ``python``. That resolves fine in a
    logged-in shell, where ``PATH`` carries
    ``%LOCALAPPDATA%\\Programs\\Python\\Python314``. The Task Scheduler
    does not inherit that PATH, so the same line dies with
    ``"python" is not recognized`` -- into a hidden window created by
    ``wscript``, where nobody sees it. The task reports Last Result 0,
    because ``wscript`` started successfully; what it started did not.

    That is why the PC failed to come back from three consecutive
    updates while every layer reported success: v4.169.21 taught the
    mover to poll the port instead of trusting an exit code, and it
    correctly found nothing listening -- but the reason was one word in
    a batch file.

    ``sys.executable`` is an absolute path to the interpreter that is
    running right now, which is by definition the right one. ``py -3``
    is the fallback: the launcher lives in ``System32`` and is on every
    PATH, including the scheduler's.
    """
    candidate = sys.executable
    if candidate and Path(candidate).is_file():
        return f'"{candidate}"'
    return "py -3"


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
    python = os.environ.get("ARENA_PYTHON") or _python_for_scheduler()

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


def repair_bare_python(root: Path) -> dict[str, Any]:
    """Rewrite a launcher whose interpreter the scheduler cannot find.

    ``write_windows_launchers`` never overwrites an existing file, which
    is right -- a hand-tuned launcher outranks a default. But a file
    written by an older version invokes a bare ``python``, and that is
    not a preference, it is a launcher that cannot launch. Leaving it
    alone means the machine keeps failing to come back in exactly the
    way that was just diagnosed.

    Only the interpreter token is replaced, and only when it is bare.
    An absolute path, a ``py -3``, or anything else the operator chose
    is left untouched.
    """
    bat = root / "start_bridge.bat"
    if not bat.is_file():
        return {"ok": False, "reason": "start_bridge.bat does not exist"}
    try:
        text = bat.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "reason": f"unreadable: {exc}"}

    lines = text.splitlines()
    fixed: list[str] = []
    changed = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("python ") or stripped.startswith("python\t"):
            fixed.append(line.replace("python", _python_for_scheduler(), 1))
            changed = True
        else:
            fixed.append(line)
    if not changed:
        return {"ok": True, "changed": False,
                "reason": "interpreter is already absolute or launcher-based"}

    backup = root / "start_bridge.bat.bak"
    try:
        backup.write_text(text, encoding="utf-8")
        bat.write_bytes(("\r\n".join(fixed) + "\r\n").encode("utf-8"))
    except OSError as exc:
        return {"ok": False, "reason": f"could not write: {exc}"}
    return {"ok": True, "changed": True, "backup": str(backup),
            "interpreter": _python_for_scheduler()}


def repair() -> dict[str, Any]:
    sysname = platform.system().lower()
    if sysname == "windows":
        root = _root()
        vbs = root / "start_hidden.vbs"
        # v4.169.21: write them rather than refusing. "Rerun install.bat"
        # is not an instruction a remote agent -- or an operator whose
        # bridge is already down -- can act on.
        written = write_windows_launchers(root)
        # An existing launcher is not overwritten above, so a bare
        # `python` written by an older version survives untouched --
        # and that is the exact defect that kept the PC down.
        bare = repair_bare_python(root)
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
                "platform": "windows", "launchers": written,
                "bare_python_fix": bare, "primary": res,
                "fallback": fallback, "status": _windows_status()}
    if sysname == "linux":
        res = _run(["systemctl", "--user", "enable", "--now", "arena-bridge.service"], timeout=20)
        return {"ok": bool(res.get("ok")), "platform": "linux", "result": res, "status": _linux_status()}
    if sysname == "darwin":
        return {"ok": False, "platform": "darwin", "error": "launchd repair is not implemented; rerun install.sh"}
    return {"ok": False, "platform": sysname, "error": "unsupported platform"}
