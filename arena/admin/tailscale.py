"""Tailscale/funnel admin runtime helpers."""
from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from typing import Any

from arena.admin.binaries import which_windows_or_path


def sys_funnel_status(*, subprocess_kwargs: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Synchronous helper to check Tailscale funnel status."""
    result: dict[str, Any] = {"ok": True, "tailscale": {}, "funnel": {}}

    try:
        out = subprocess.check_output(["tailscale", "status"], stderr=subprocess.STDOUT, text=True, **subprocess_kwargs())
        result["tailscale"]["status"] = out.strip()[:2000]
        result["tailscale"]["connected"] = bool(out.strip())
    except FileNotFoundError:
        result["tailscale"]["error"] = "tailscale not found"
    except Exception as e:
        result["tailscale"]["error"] = str(e)[:500]

    try:
        out = subprocess.check_output(["tailscale", "funnel", "status"], stderr=subprocess.STDOUT, text=True, **subprocess_kwargs())
        result["funnel"]["status"] = out.strip()[:2000]
        lw = out.lower()
        result["funnel"]["active"] = (
            "funnel on" in lw
            or "proxy http" in lw
            or "serving" in lw
            or "listening" in lw
        )
        match = re.search(r"https://[\w.-]+\.ts\.net[^\s]*", out)
        if match:
            result["funnel"]["url"] = match.group(0)
    except FileNotFoundError:
        result["funnel"]["error"] = "tailscale not found"
    except Exception as e:
        result["funnel"]["error"] = str(e)[:500]

    return result


def tailscale_funnel_action(action: str, port: int) -> dict[str, Any]:
    action = (action or "").lower()
    if action not in ("start", "stop", "status"):
        return {"ok": False, "error": "action must be start|stop|status"}

    ts = which_windows_or_path(
        "tailscale",
        [
            r"C:\Program Files\Tailscale\tailscale.exe",
            r"C:\Program Files (x86)\Tailscale\tailscale.exe",
        ],
    )
    if not ts:
        return {"ok": False, "error": "tailscale binary not found"}

    if action == "start":
        try:
            result = subprocess.run([ts, "funnel", "--bg", str(port)], capture_output=True, text=True, timeout=15)
            return {"ok": result.returncode == 0, "action": "start", "port": port,
                    "stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if action == "stop":
        try:
            result = subprocess.run([ts, "funnel", "--https=443", "off"], capture_output=True, text=True, timeout=15)
            return {"ok": result.returncode == 0, "action": "stop",
                    "stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    try:
        result = subprocess.run([ts, "funnel", "status"], capture_output=True, text=True, timeout=10)
        out = result.stdout or ""
        return {"ok": True, "action": "status", "output": out,
                "active": ("funnel on" in out.lower() or "proxy http" in out.lower())}
    except Exception as e:
        return {"ok": False, "error": str(e)}
