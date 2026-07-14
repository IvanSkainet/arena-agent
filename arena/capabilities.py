"""Agent-facing capability map builder.

The `/v1/capabilities` contract is intentionally stable across platforms: the
same sections are returned on Windows/Linux/macOS/headless hosts, while
`available`, `backend`, and `reason` fields describe platform-specific reality.

This module is deliberately independent from aiohttp and the bridge monolith.
Runtime-specific state (CDP connection, desktop environment detection, service
status callbacks) is injected by the caller to avoid circular imports.
"""
from __future__ import annotations

import platform
import shutil
import socket
import sys
from typing import Any, Callable


def build_capabilities(
    *,
    version: str,
    cdp_module_available: bool,
    cdp_connected: bool,
    desktop_env: dict[str, Any] | None,
    service_info_fn: Callable[[], dict[str, Any]],
    sys_svc_fn: Callable[[], dict[str, Any]],
    zerotier_status_fn: Callable[[], dict[str, Any]] | None = None,
    browseract_status_fn: Callable[[], dict[str, Any]] | None = None,
    mobile_status_fn: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a machine-readable capability map for agents."""
    env = desktop_env or {}
    desktop_name = env.get("desktop") or env.get("desktop_session") or ("Windows" if sys.platform == "win32" else "")
    session_name = env.get("session_type") or ("windows" if sys.platform == "win32" else "")
    caps: dict[str, Any] = {
        "ok": True,
        "version": version,
        "platform": {
            "system": platform.system().lower(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "host": socket.gethostname(),
        },
        "api": {
            "rest": True,
            "mcp_http": True,
            "mcp_sse": True,
            "websocket": True,
            "dashboard": True,
        },
        "system": {
            "exec": True,
            "tasks": True,
            "skills": True,
            "hardware": True,
            "memory": True,
            "audit": True,
        },
        "browser": {
            "fetch_read": True,
            "cdp_module": bool(cdp_module_available),
            "cdp_connected": bool(cdp_connected),
            "cdp_aliases": True,
        },
        "desktop": {
            "available": False,
            "session": session_name,
            "desktop": desktop_name,
            "windows": {"available": False, "backend": "none"},
            "active_window": {"available": False, "backend": "none"},
            "screenshot": {"available": False, "backend": "none"},
            "input": {"available": False, "backend": "none"},
        },
        "service": {},
        "network": {},
        "warnings": [],
    }

    if sys.platform == "win32":
        caps["service"] = service_info_fn()
        caps["desktop"].update({
            "available": False,
            "windows": {"available": False, "backend": "pending-win32", "reason": "Windows desktop backend is not implemented yet"},
            "active_window": {"available": False, "backend": "pending-win32", "reason": "Windows desktop backend is not implemented yet"},
            "screenshot": {"available": False, "backend": "pending-win32", "reason": "Windows screenshot backend is not implemented yet"},
            "input": {"available": False, "backend": "pending-win32", "reason": "Windows SendInput backend is not implemented yet"},
        })
        caps["warnings"].append("Windows core is supported; desktop automation backend is pending")
    elif sys.platform == "linux":
        is_kde = "kde" in desktop_name.lower() or "plasma" in desktop_name.lower()
        wayland = bool(env.get("wayland"))
        kwin_available = is_kde and wayland and bool(shutil.which("qdbus6") or shutil.which("qdbus"))
        windows_backend = (
            "kwin_journal"
            if (kwin_available and shutil.which("journalctl"))
            else ("wmctrl" if shutil.which("wmctrl") else ("xdotool" if env.get("has_xdotool") else "none"))
        )
        active_backend = windows_backend
        screenshot_backend = "spectacle" if env.get("has_spectacle") else ("grim" if env.get("has_grim") else ("scrot" if env.get("has_scrot") else "none"))
        input_backend = "ydotool" if env.get("has_ydotool") else ("wtype" if env.get("has_wtype") else ("xdotool" if env.get("has_xdotool") else "none"))
        caps["desktop"].update({
            "available": windows_backend != "none" or screenshot_backend != "none" or input_backend != "none",
            "wayland": wayland,
            "x11": bool(env.get("x11")),
            "windows": {"available": windows_backend != "none", "backend": windows_backend},
            "active_window": {"available": active_backend != "none", "backend": active_backend},
            "screenshot": {"available": screenshot_backend != "none", "backend": screenshot_backend},
            "input": {"available": input_backend != "none", "backend": input_backend},
        })
        caps["service"] = service_info_fn()
    elif sys.platform == "darwin":
        caps["service"] = service_info_fn()
        caps["desktop"].update({
            "available": False,
            "windows": {"available": False, "backend": "pending-macos"},
            "screenshot": {"available": shutil.which("screencapture") is not None, "backend": "screencapture" if shutil.which("screencapture") else "none"},
            "input": {"available": False, "backend": "pending-macos"},
        })

    try:
        svc = sys_svc_fn()
        ts = svc.get("tailscale") or {}
        caps["network"] = {
            "tailscale_installed": bool(ts.get("installed")),
            "tailscale_connected": bool(ts.get("connected")),
            "funnel_hint": "Use /v1/sys/funnel for current public URL/status",
        }
    except Exception:
        pass

    # BrowserAct stealth-browser CLI (skills/browseract).
    if browseract_status_fn is not None:
        try:
            ba = browseract_status_fn() or {}
            caps["browser"].update({
                "browseract_installed": bool(ba.get("installed")),
                "browseract_version": ba.get("version"),
                "browseract_cli_source": ba.get("cli_source"),
                "browseract_cli_path": ba.get("cli_path"),
                "browseract_update_hint": ba.get("update_hint") or ba.get("hint"),
            })
        except Exception as e:
            caps["browser"]["browseract_error"] = str(e)[:200]

    # ZeroTier as a backup remote-access provider.
    if zerotier_status_fn is not None:
        try:
            zt = zerotier_status_fn() or {}
            zt_info = zt.get("zerotier") or {}
            networks = zt.get("networks") or []
            caps.setdefault("network", {})
            caps["network"].update({
                "zerotier_installed": bool(zt.get("installed")),
                "zerotier_backend": zt.get("backend"),
                "zerotier_cli_source": zt.get("cli_source"),
                "zerotier_connected": bool(zt_info.get("connected")),
                "zerotier_node_id": zt_info.get("node_id"),
                "zerotier_version": zt_info.get("version"),
                "zerotier_active_networks": sum(1 for n in networks if n.get("active")),
                "zerotier_hint": zt.get("hint")
                    or "Use /v1/zerotier/status for full state; /v1/zerotier/network/{join,leave,status} to manage",
            })
        except Exception as e:
            caps.setdefault("network", {})["zerotier_error"] = str(e)[:200]

    # Mobile (Android via ADB) — Phase 1 companion layer.
    if mobile_status_fn is not None:
        try:
            m = mobile_status_fn() or {}
            caps["mobile"] = {
                "available": bool(m.get("adb_installed")),
                "backend": "adb",
                "adb_path": m.get("adb_path"),
                "adb_version": m.get("adb_version"),
                "devices": len(m.get("devices") or []),
                "device_serials": [d.get("serial") for d in (m.get("devices") or [])],
                "endpoints": [
                    "devices", "info", "screenshot",
                    "tap", "swipe", "type", "key",
                    "shell", "packages", "gesture", "ui", "tap_by",
                ],
                "hint": m.get("hint"),
            }
        except Exception as e:
            caps["mobile"] = {"available": False, "backend": "adb", "error": str(e)[:200]}

    return caps
