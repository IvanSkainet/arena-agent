"""ZeroTier network admin runtime helpers."""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any


def zerotier_status(*, subprocess_kwargs: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Synchronous helper to check ZeroTier status."""
    result: dict[str, Any] = {"ok": True, "zerotier": {}, "networks": []}

    try:
        out = subprocess.check_output(
            ["zerotier-cli", "status"],
            stderr=subprocess.STDOUT,
            text=True,
            **subprocess_kwargs()
        )
        result["zerotier"]["status"] = out.strip()[:2000]
        # Parse: "200 info <node-id> <version> ONLINE"
        parts = out.strip().split()
        if len(parts) >= 4:
            result["zerotier"]["connected"] = "ONLINE" in out.upper()
            result["zerotier"]["node_id"] = parts[2] if len(parts) > 2 else None
            result["zerotier"]["version"] = parts[3] if len(parts) > 3 else None
    except FileNotFoundError:
        result["zerotier"]["error"] = "zerotier-cli not found"
    except Exception as e:
        result["zerotier"]["error"] = str(e)[:500]

    try:
        out = subprocess.check_output(
            ["zerotier-cli", "listnetworks"],
            stderr=subprocess.STDOUT,
            text=True,
            **subprocess_kwargs()
        )
        # Parse network list
        for line in out.strip().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            # Format: "200 listnetworks <net-id> <nwid> <type> <status> <mac>"
            parts = line.split()
            if len(parts) >= 6 and parts[1] == "listnetworks":
                network = {
                    "id": parts[2],
                    "nwid": parts[3],
                    "type": parts[4],
                    "status": parts[5],
                    "active": parts[5].upper() == "OK",
                }
                result["networks"].append(network)
    except FileNotFoundError:
        result["zerotier"]["error"] = "zerotier-cli not found"
    except Exception as e:
        result["zerotier"]["error"] = str(e)[:500]

    return result


def zerotier_network_action(action: str, network_id: str | None = None) -> dict[str, Any]:
    """Perform ZeroTier network action (join/leave/status)."""
    action = (action or "").lower()
    if action not in ("join", "leave", "status"):
        return {"ok": False, "error": "action must be join|leave|status"}

    if action in ("join", "leave") and not network_id:
        return {"ok": False, "error": f"network_id required for {action}"}

    # Find zerotier-cli binary
    zt = None
    for path in [
        "zerotier-cli",
        "/usr/sbin/zerotier-cli",
        "/usr/local/bin/zerotier-cli",
    ]:
        try:
            subprocess.run([path, "status"], capture_output=True, timeout=5)
            zt = path
            break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    if not zt:
        return {"ok": False, "error": "zerotier-cli binary not found"}

    if action == "join":
        try:
            result = subprocess.run(
                [zt, "join", network_id],
                capture_output=True,
                text=True,
                timeout=15
            )
            return {
                "ok": result.returncode == 0,
                "action": "join",
                "network_id": network_id,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if action == "leave":
        try:
            result = subprocess.run(
                [zt, "leave", network_id],
                capture_output=True,
                text=True,
                timeout=15
            )
            return {
                "ok": result.returncode == 0,
                "action": "leave",
                "network_id": network_id,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # action == "status"
    try:
        result = subprocess.run(
            [zt, "listnetworks"],
            capture_output=True,
            text=True,
            timeout=10
        )
        out = result.stdout or ""
        networks = []
        for line in out.strip().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 6 and parts[1] == "listnetworks":
                networks.append({
                    "id": parts[2],
                    "status": parts[5],
                    "active": parts[5].upper() == "OK",
                })
        return {
            "ok": True,
            "action": "status",
            "output": out,
            "networks": networks,
            "active_count": sum(1 for n in networks if n["active"]),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
