"""Whole-ship status / preflight map.

This is intentionally broader than ``workbench.status``: it is the bridge's
"flight computer" map across transports, posture, desktop/browser/MCP,
mobile/ADB and the code workbench.  Every probe is fail-soft: a broken
subsystem becomes a degraded item in the map, never an exception that hides
the rest of the ship.
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import sys
from pathlib import Path
from typing import Any, Callable

from arena.autonomy import posture as _posture
from arena.constants import VERSION
from arena.util import _subprocess_kwargs


def _safe(name: str, fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as e:  # pragma: no cover - defensive boundary
        return {"ok": False, "component": name, "error": f"{type(e).__name__}: {e}"[:500]}


def _root() -> str:
    return str(Path(os.environ.get("ARENA_AGENT_HOME") or Path.home() / "arena-bridge"))


def _bridge_status() -> dict[str, Any]:
    service_status = _safe("service", lambda: __import__("arena.service.status", fromlist=["_sys_svc_sync"])._sys_svc_sync())
    return {
        "ok": True,
        "version": VERSION,
        "service": "arena-unified-bridge",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "root": _root(),
        "service_status": service_status,
    }


def _transport_status() -> dict[str, Any]:
    from arena.admin.tailscale import sys_funnel_status
    from arena.admin.tunnels import tunnels_status

    return tunnels_status(
        port=int(os.environ.get("ARENA_PORT", "8765") or 8765),
        sys_funnel_status_sync=lambda: sys_funnel_status(subprocess_kwargs=_subprocess_kwargs),
    )


def _mcp_status() -> dict[str, Any]:
    from arena.mcp_client import get_manager

    mgr = get_manager()
    servers = []
    for name, cfg in sorted(mgr.servers().items()):
        st = _safe(f"mcp:{name}", lambda n=name: mgr.status(n))
        servers.append({
            "name": name,
            "command": cfg.get("command", ""),
            "args": cfg.get("args", []),
            "running": bool((st or {}).get("running")),
            "status": st,
        })
    by_name = {s["name"]: s for s in servers}
    return {
        "ok": True,
        "count": len(servers),
        "servers": servers,
        "desktop_commander": by_name.get("desktop-commander"),
        "screenpilot": by_name.get("screenpilot"),
    }


def _browser_binary() -> str | None:
    candidates = [
        "msedge", "msedge.exe", "chrome", "chrome.exe", "chromium", "chromium-browser",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        p = shutil.which(c) or (c if os.path.isfile(c) else None)
        if p:
            return p
    return None


def _port_open(port: int) -> bool | str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            return sock.connect_ex(("127.0.0.1", port)) == 0
    except Exception as e:  # pragma: no cover - platform defensive
        return f"unknown: {e}"


def _browser_status() -> dict[str, Any]:
    from arena.admin.browseract import browseract_status

    browseract = _safe("browseract", browseract_status)
    return {
        "ok": True,
        "browseract": browseract,
        "cdp": {
            "ok": True,
            "port": 9222,
            "port_open": _port_open(9222),
            "browser_binary": _browser_binary(),
            "known_limit": "Windows service/session isolation may leave CDP without an active tab.",
        },
    }


def _mobile_status() -> dict[str, Any]:
    from arena.mobile.adb import adb_version, find_adb
    from arena.mobile.devices import list_devices

    devices = _safe("mobile.devices", list_devices)
    return {
        "ok": bool((devices or {}).get("ok")),
        "adb_path": find_adb(),
        "adb_version": adb_version(),
        "devices": devices,
    }


def _desktop_status(mcp: dict[str, Any]) -> dict[str, Any]:
    screenpilot = mcp.get("screenpilot")
    commander = mcp.get("desktop_commander")
    return {
        "ok": True,
        "screenpilot_registered": bool(screenpilot),
        "screenpilot_running": bool((screenpilot or {}).get("running")),
        "desktop_commander_registered": bool(commander),
        "desktop_commander_running": bool((commander or {}).get("running")),
        "note": "Desktop actuation is intentionally surfaced through explicit MCP servers/tools; this status does not move the mouse or type.",
    }


def _known_issues(parts: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    wb_limits = (((parts.get("workbench") or {}).get("known_limits")) or [])
    for item in wb_limits:
        if isinstance(item, dict):
            issues.append({
                "component": str(item.get("component", "unknown")),
                "status": str(item.get("status", "degraded")),
                "reason": str(item.get("reason", "")),
            })

    posture = parts.get("posture") or {}
    if posture.get("risk") not in ("low", "medium"):
        issues.append({"component": "posture", "status": "critical", "reason": "Operator posture is not low/medium; restore fenced low-risk defaults before autonomous work."})

    transports = parts.get("transports") or {}
    if not transports.get("active"):
        issues.append({"component": "transport", "status": "degraded", "reason": "No active public/tailnet transport selected by tunnel status."})

    mobile = parts.get("mobile") or {}
    devices = ((mobile.get("devices") or {}).get("devices") or []) if isinstance(mobile, dict) else []
    if mobile and not devices:
        issues.append({"component": "mobile.adb", "status": "degraded", "reason": "ADB is absent or no Android device is currently visible."})

    browseract = (((parts.get("browser") or {}).get("browseract")) or {})
    if browseract and not browseract.get("installed"):
        issues.append({"component": "browseract", "status": "degraded", "reason": "BrowserAct CLI is not visible to the bridge process."})
    return issues


def _next_actions(parts: dict[str, Any], issues: list[dict[str, str]]) -> list[str]:
    actions: list[str] = []
    if any(i["component"] == "posture" for i in issues):
        actions.append("Restore low-risk AppContainer/scratch-only/network-deny posture before continuing autonomous work.")
    if any(i["component"] == "transport" for i in issues):
        actions.append("Verify Tailscale Funnel or another transport so the observer and agent keep a stable route to the bridge.")
    if any(i["component"] == "mobile.adb" for i in issues):
        actions.append("For phone work: connect/authorize POCO via USB or wireless ADB; do not cross lock/PIN boundaries automatically.")
    if any(i["component"] == "browseract" for i in issues):
        actions.append("Keep BrowserAct listed as blocked/degraded until its local CDP proxy exposes /json/version in a real desktop session.")
    if not actions:
        actions.append("Ship map is coherent enough for the next roadmap item: Tool Foundry v1.")
    actions.append("Use ship.preflight before multi-step scenarios, releases, or hardware/browser/phone work.")
    return actions


def status() -> dict[str, Any]:
    """Return the whole-ship map. Read-only; no mouse/keyboard/browser launch."""
    bridge = _safe("bridge", _bridge_status)
    posture = _safe("posture", _posture.get_posture)
    workbench = _safe("workbench", lambda: __import__("arena.workbench.status", fromlist=["status"]).status())
    transports = _safe("transports", _transport_status)
    mcp = _safe("mcp", _mcp_status)
    browser = _safe("browser", _browser_status)
    mobile = _safe("mobile", _mobile_status)
    desktop = _safe("desktop", lambda: _desktop_status(mcp if isinstance(mcp, dict) else {}))
    parts = {
        "bridge": bridge,
        "posture": posture,
        "transports": transports,
        "mcp": mcp,
        "desktop": desktop,
        "browser": browser,
        "mobile": mobile,
        "workbench": workbench,
    }
    issues = _known_issues(parts)
    risk = str((posture or {}).get("risk") or "unknown")
    return {
        "ok": True,
        "ship": "arena-unified-bridge",
        "version": VERSION,
        "risk": risk,
        **parts,
        "known_issues": issues,
        "next_actions": _next_actions(parts, issues),
        "roadmap": "docs/dynamic_harness_roadmap.md",
    }


def _check(name: str, ok: bool, *, severity: str = "fail", detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "severity": severity, "detail": detail}


def preflight() -> dict[str, Any]:
    """Summarise readiness for real work without pretending optional subsystems are fatal."""
    snap = status()
    posture = snap.get("posture") or {}
    transports = snap.get("transports") or {}
    workbench = snap.get("workbench") or {}
    browser = snap.get("browser") or {}
    mobile = snap.get("mobile") or {}
    mcp = snap.get("mcp") or {}

    checks = [
        _check("bridge.version", bool(snap.get("version")), detail=str(snap.get("version"))),
        _check("posture.low_or_medium", posture.get("risk") in ("low", "medium"), detail=f"risk={posture.get('risk')}") ,
        _check("transport.active", bool(transports.get("active")), severity="warn", detail=str(transports.get("active") or "none")),
        _check("workbench.status", bool(workbench.get("ok")), detail=f"projects={(workbench.get('projects') or {}).get('count')} sessions={(workbench.get('sessions') or {}).get('count')}"),
        _check("mcp.registry", bool(mcp.get("ok")), severity="warn", detail=f"servers={mcp.get('count') if isinstance(mcp, dict) else 'unknown'}"),
        _check("browser.cdp_or_browseract_visible", bool(((browser.get("cdp") or {}).get("browser_binary")) or ((browser.get("browseract") or {}).get("installed"))), severity="warn"),
        _check("mobile.adb_device_visible", bool(((mobile.get("devices") or {}).get("devices") or [])), severity="warn"),
    ]
    failed = [c for c in checks if not c["ok"] and c["severity"] == "fail"]
    warnings = [c for c in checks if not c["ok"] and c["severity"] == "warn"]
    return {
        "ok": not failed,
        "ready": not failed,
        "mode": "degraded" if warnings and not failed else ("blocked" if failed else "nominal"),
        "checks": checks,
        "failed": failed,
        "warnings": warnings,
        "known_issues": snap.get("known_issues", []),
        "next_actions": snap.get("next_actions", []),
        "status": snap,
    }
