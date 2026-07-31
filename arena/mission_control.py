"""Mission Control: unified observer dashboard aggregator.

v4.150.0 — Provides a single read-only view of the entire ship state:
ship mode, latest autopilot runs, open capability gaps, scenario flight
records, and active subsystems.  Designed to replace verbose chat reporting
with a single structured snapshot.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any


def _now() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _mcp_call_safe(port: int, token: str, tool: str, arguments: dict[str, Any] | None = None, timeout: int = 15) -> dict[str, Any]:
    """Best-effort MCP tool call; never raises."""
    try:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments or {}}}
        req = urllib.request.Request(
            f"http://127.0.0.1:{int(port)}/mcp",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=max(1, int(timeout))) as resp:  # nosec B310 -- loopback-only MCP dispatch; nosemgrep: dynamic-urllib-use-detected -- URL is fixed to 127.0.0.1
            outer = json.loads(resp.read().decode("utf-8", "replace"))
        content = (outer.get("result") or {}).get("content") or []
        text = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
        try:
            return json.loads(text) if text else {}
        except Exception:
            return {"text": text}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def control_status(*, port: int = 8765, token: str = "") -> dict[str, Any]:
    """Aggregate the entire ship state into a single observer snapshot."""

    # Ship preflight (mode, readiness)
    preflight = _mcp_call_safe(port, token, "ship.preflight")

    # Determine ship mode
    mode = preflight.get("mode", "unknown")
    ready = preflight.get("ready", False)
    failed_checks = preflight.get("failed", [])

    # Latest autopilot runs
    from arena import mission_autopilot as _ap
    autopilot_runs = _ap.list_runs(limit=5)

    # Open capability gaps
    from arena import capability_gaps as _gaps
    open_gaps = _gaps.list_gaps(status="open", limit=10)

    # Scenario flight records
    scenarios = _mcp_call_safe(port, token, "scenario.records", {"limit": 5})

    # Active desktop windows (lightweight)
    desktop = _mcp_call_safe(port, token, "desktop.windows", {"limit": 10})
    window_count = len((desktop.get("windows") or desktop.get("result", {}).get("windows", [])) if isinstance(desktop, dict) else [])

    # Mobile devices
    mobile = _mcp_call_safe(port, token, "mobile.preflight")
    mobile_ok = mobile.get("ok", False)
    mobile_devices = mobile.get("devices", [])

    # Build the dashboard
    dashboard: dict[str, Any] = {
        "ok": True,
        "timestamp": _now(),
        "ship": {
            "mode": mode,
            "ready": ready,
            "failed_checks": failed_checks,
        },
        "autopilot": {
            "recent_runs": autopilot_runs.get("runs", []),
            "total": autopilot_runs.get("count", 0),
        },
        "capability_gaps": {
            "open_count": open_gaps.get("count", 0),
            "gaps": [{"id": g.get("id"), "title": g.get("title"), "severity": g.get("severity")} for g in open_gaps.get("gaps", [])],
        },
        "scenarios": {
            "recent_records": scenarios.get("records", [])[:5] if isinstance(scenarios.get("records"), list) else [],
        },
        "desktop": {
            "window_count": window_count,
        },
        "mobile": {
            "ok": mobile_ok,
            "device_count": len(mobile_devices) if isinstance(mobile_devices, list) else 0,
        },
    }

    return dashboard


__all__ = ["control_status"]
