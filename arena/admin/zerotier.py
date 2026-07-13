"""ZeroTier network admin runtime helpers.

The Bridge often runs as a non-root user that cannot read
/var/lib/zerotier-one/authtoken.secret. To work around this we prefer a
sudo wrapper (e.g. /usr/local/bin/zerotier-cli-wrapper) when it is
available. The wrapper is expected to be a small shell script that
exec's `sudo /usr/bin/zerotier-cli "$@"` and must be paired with a
NOPASSWD sudoers rule.
"""
from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from typing import Any


_WRAPPER_CANDIDATES: tuple[str, ...] = (
    "/usr/local/bin/zerotier-cli-wrapper",
    "/usr/bin/zerotier-cli-wrapper",
)
_DIRECT_CANDIDATES: tuple[str, ...] = (
    "zerotier-cli",
    "/usr/sbin/zerotier-cli",
    "/usr/bin/zerotier-cli",
    "/usr/local/bin/zerotier-cli",
)


def _cli_binary() -> tuple[str | None, str]:
    """Return (path, source) for the best zerotier CLI available.

    source is one of: "wrapper", "direct", "not_found".
    Wrapper is preferred because Bridge normally runs unprivileged.
    """
    for path in _WRAPPER_CANDIDATES:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path, "wrapper"
    for path in _DIRECT_CANDIDATES:
        # For bare name, rely on subprocess PATH lookup at call time.
        if path == "zerotier-cli":
            return path, "direct"
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path, "direct"
    return None, "not_found"


def _run(cli: str, args: list[str], timeout: int, extra_kwargs: dict[str, Any] | None = None) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
    }
    if extra_kwargs:
        # Never let caller override our capture/text settings.
        for k, v in extra_kwargs.items():
            if k not in ("capture_output", "text", "stdout", "stderr"):
                kwargs[k] = v
    return subprocess.run([cli, *args], **kwargs)


def _parse_listnetworks(out: str) -> list[dict[str, Any]]:
    networks: list[dict[str, Any]] = []
    for line in (out or "").strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Format: "200 listnetworks <nwid> <name> <mac> <status> <type> <dev> <ips>"
        parts = line.split()
        if len(parts) >= 6 and parts[1] == "listnetworks":
            # Skip header row where columns are literal placeholders
            if parts[2] == "<nwid>" or parts[3] == "<name>":
                continue
            status = parts[5]
            networks.append({
                "id": parts[2],
                "nwid": parts[2],
                "name": parts[3] if len(parts) > 3 else "",
                "mac": parts[4] if len(parts) > 4 else "",
                "status": status,
                "type": parts[6] if len(parts) > 6 else "",
                "active": status.upper() == "OK",
            })
    return networks


def zerotier_status(*, subprocess_kwargs: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Synchronous helper to check ZeroTier status and list networks."""
    cli, source = _cli_binary()
    result: dict[str, Any] = {
        "ok": True,
        "cli_path": cli,
        "cli_source": source,
        "zerotier": {},
        "networks": [],
    }

    if not cli:
        result["ok"] = False
        result["zerotier"]["error"] = "zerotier-cli not found (install zerotier-one or create a sudo wrapper)"
        return result

    extra = subprocess_kwargs() if subprocess_kwargs else {}

    # status
    try:
        proc = _run(cli, ["status"], timeout=10, extra_kwargs=extra)
        out = (proc.stdout or "") + (proc.stderr or "" if proc.returncode != 0 else "")
        if proc.returncode != 0:
            result["zerotier"]["error"] = out.strip()[:500] or f"exit={proc.returncode}"
        else:
            text = (proc.stdout or "").strip()
            result["zerotier"]["status"] = text[:2000]
            parts = text.split()
            if len(parts) >= 4:
                result["zerotier"]["node_id"] = parts[2]
                result["zerotier"]["version"] = parts[3]
                result["zerotier"]["connected"] = "ONLINE" in text.upper() or "TUNNELED" in text.upper()
    except FileNotFoundError:
        result["zerotier"]["error"] = "zerotier-cli not found"
        result["ok"] = False
        return result
    except Exception as e:
        result["zerotier"]["error"] = str(e)[:500]

    # listnetworks
    try:
        proc = _run(cli, ["listnetworks"], timeout=10, extra_kwargs=extra)
        if proc.returncode == 0:
            result["networks"] = _parse_listnetworks(proc.stdout or "")
        else:
            msg = ((proc.stderr or "") + (proc.stdout or "")).strip()
            result["zerotier"].setdefault("listnetworks_error", msg[:500] or f"exit={proc.returncode}")
    except Exception as e:
        result["zerotier"].setdefault("listnetworks_error", str(e)[:500])

    result["active_count"] = sum(1 for n in result["networks"] if n.get("active"))
    return result


def zerotier_network_action(action: str, network_id: str | None = None) -> dict[str, Any]:
    """Perform ZeroTier network action (join/leave/status)."""
    action = (action or "").lower()
    if action not in ("join", "leave", "status"):
        return {"ok": False, "error": "action must be join|leave|status"}

    if action in ("join", "leave") and not network_id:
        return {"ok": False, "error": f"network_id required for {action}"}

    cli, source = _cli_binary()
    if not cli:
        return {"ok": False, "error": "zerotier-cli not found", "cli_source": source}

    if action in ("join", "leave"):
        try:
            proc = _run(cli, [action, network_id], timeout=15)
            return {
                "ok": proc.returncode == 0,
                "action": action,
                "network_id": network_id,
                "cli_source": source,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "exit_code": proc.returncode,
            }
        except Exception as e:
            return {"ok": False, "action": action, "error": str(e)}

    # action == "status"
    try:
        proc = _run(cli, ["listnetworks"], timeout=10)
        networks = _parse_listnetworks(proc.stdout or "") if proc.returncode == 0 else []
        return {
            "ok": proc.returncode == 0,
            "action": "status",
            "cli_source": source,
            "output": proc.stdout,
            "networks": networks,
            "active_count": sum(1 for n in networks if n["active"]),
            "exit_code": proc.returncode,
        }
    except Exception as e:
        return {"ok": False, "action": "status", "error": str(e)}
