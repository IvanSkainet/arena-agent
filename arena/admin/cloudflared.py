"""Cloudflared tunnel admin runtime helpers with system-first strategy."""
from __future__ import annotations

import platform
import re
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arena.admin.binaries import which_windows_or_path

CLOUDFLARED_STATE: dict[str, Any] = {"proc": None, "url": "", "log": []}


def _cloudflared_monitor_thread(proc: subprocess.Popen, port: int) -> None:
    while True:
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            break
        line_str = line.strip()
        CLOUDFLARED_STATE["log"].append(line_str)
        if len(CLOUDFLARED_STATE["log"]) > 100:
            CLOUDFLARED_STATE["log"].pop(0)
        match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line_str)
        if match:
            CLOUDFLARED_STATE["url"] = match.group(0)


def _resolve_cloudflared_with_source(root_agent: Path) -> tuple[str | None, str]:
    """Resolve cloudflared binary and determine its source.
    
    Returns:
        (path, source) where source is "system", "bundled", or "not_found"
    """
    # 1. System-first: check PATH
    system_cf = which_windows_or_path(
        "cloudflared",
        [
            r"C:\Program Files\cloudflared\cloudflared.exe",
            r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        ],
    )
    if system_cf:
        return system_cf, "system"
    
    # 2. Bundled: check local directory
    local_cf = Path(root_agent) / ("cloudflared.exe" if platform.system() == "Windows" else "cloudflared")
    if local_cf.exists():
        return str(local_cf), "bundled"
    
    return None, "not_found"


def _resolve_cloudflared(root_agent: Path) -> str | None:
    """Legacy resolver for backward compatibility."""
    cf, _ = _resolve_cloudflared_with_source(root_agent)
    return cf


def _get_cloudflared_version(cf_path: str) -> str | None:
    """Get cloudflared version string."""
    try:
        result = subprocess.run(
            [cf_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        # Output: "cloudflared version 2026.7.1 (built 20260710-02:54:19)"
        match = re.search(r"version\s+([\d.]+)", result.stdout)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


def _get_update_hint(source: str, version: str | None) -> str:
    """Get update instructions based on source."""
    if source == "system":
        if platform.system() == "Linux":
            return "Update via package manager: sudo apt update && sudo apt upgrade cloudflared (or pacman -Syu cloudflared)"
        elif platform.system() == "Darwin":
            return "Update via Homebrew: brew upgrade cloudflared"
        else:
            return "Download latest from https://github.com/cloudflare/cloudflared/releases"
    elif source == "bundled":
        return "Bundled version managed by Arena. Run: python3 scripts/update_bundled_tools.py cloudflared"
    else:
        return "Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"


def _terminate_cloudflared(timeout: int = 5) -> None:
    proc = CLOUDFLARED_STATE["proc"]
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _start_cloudflared(cf: str, port: int, *, subprocess_kwargs: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    if CLOUDFLARED_STATE["proc"] and CLOUDFLARED_STATE["proc"].poll() is None:
        return {"ok": True, "action": "start", "already_running": True, "url": CLOUDFLARED_STATE["url"]}
    CLOUDFLARED_STATE["url"] = ""
    CLOUDFLARED_STATE["log"].clear()
    try:
        CLOUDFLARED_STATE["proc"] = subprocess.Popen(
            [cf, "tunnel", "--url", f"http://127.0.0.1:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            **subprocess_kwargs(),
        )
        thread = threading.Thread(target=_cloudflared_monitor_thread, args=(CLOUDFLARED_STATE["proc"], port), daemon=True)
        thread.start()

        for _ in range(20):
            if CLOUDFLARED_STATE["url"] or CLOUDFLARED_STATE["proc"].poll() is not None:
                break
            time.sleep(0.5)

        if not CLOUDFLARED_STATE["url"]:
            _terminate_cloudflared(timeout=2)
            CLOUDFLARED_STATE["proc"] = None
            return {"ok": False, "action": "start", "error": "cloudflared timed out generating a tunnel URL", "log": list(CLOUDFLARED_STATE["log"])}
        return {"ok": True, "action": "start", "port": port, "url": CLOUDFLARED_STATE["url"], "log": CLOUDFLARED_STATE["log"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def cloudflared_funnel_action(
    action: str,
    port: int,
    *,
    root_agent: Path,
    subprocess_kwargs: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    action = (action or "").lower()
    if action not in ("start", "stop", "status"):
        return {"ok": False, "error": "action must be start|stop|status"}

    cf, source = _resolve_cloudflared_with_source(root_agent)
    
    if action == "start":
        if not cf:
            return {"ok": False, "error": "cloudflared binary not found", "update_hint": _get_update_hint(source, None)}
        return _start_cloudflared(cf, port, subprocess_kwargs=subprocess_kwargs)

    if action == "stop":
        _terminate_cloudflared()
        CLOUDFLARED_STATE["proc"] = None
        CLOUDFLARED_STATE["url"] = ""
        return {"ok": True, "action": "stop"}

    # action == "status"
    proc = CLOUDFLARED_STATE["proc"]
    running = proc is not None and proc.poll() is None
    installed = cf is not None
    version = _get_cloudflared_version(cf) if cf else None
    
    result = {
        "ok": True,
        "action": "status",
        "installed": installed,
        "source": source,
        "version": version,
        "active": running,
        "url": CLOUDFLARED_STATE["url"],
        "log": CLOUDFLARED_STATE["log"] if running else [],
    }
    
    if installed:
        result["update_hint"] = _get_update_hint(source, version)
    
    return result
