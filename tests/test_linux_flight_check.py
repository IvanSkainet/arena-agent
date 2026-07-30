"""v4.136.0 -- Linux/CachyOS flight check."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.mcp.tool_ship import handle_ship_tool  # noqa: E402
from arena.ship import linux_flight as L  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_linux_flight_tool_registered_and_safe():
    assert "ship.linux_flight_check" in {t["name"] for t in MCP_TOOLS}
    assert classify_tool_risk("ship.linux_flight_check") == "safe"


def test_linux_flight_shape(monkeypatch):
    monkeypatch.setattr(L.platform, "system", lambda: "Linux")
    monkeypatch.setattr(L.platform, "platform", lambda: "Linux-test")
    monkeypatch.setattr(L.platform, "python_version", lambda: "3.x")
    monkeypatch.setattr(L.shutil, "which", lambda name: "/bin/" + name if name in {"systemd-run", "tailscale"} else None)
    monkeypatch.setattr(L, "_run", lambda cmd, timeout=8: {"ok": True, "stdout": "active\n", "stderr": "", "exit": 0})
    monkeypatch.setattr(L.runtimes, "probe", lambda: {"ok": True, "runtimes": {}})
    monkeypatch.setattr(L.runtime_compat, "build", lambda rt: {"ok": True, "matrix": []})
    monkeypatch.setattr(L.mobile_preflight, "preflight", lambda: {"ready": True, "selected_serial": "s"})
    monkeypatch.setattr(L, "sys_funnel_status", lambda subprocess_kwargs: {"ok": True})
    out = L.status()
    assert out["ok"] is True
    assert out["mode"] == "nominal"
    assert {"host", "service", "desktop", "tailscale", "mobile", "browser", "runtimes", "runtime_compat", "checks"} <= set(out)


def test_linux_flight_mcp_tool(monkeypatch):
    monkeypatch.setattr(L, "status", lambda: {"ok": True, "mode": "nominal"})
    out = _parsed(handle_ship_tool("ship.linux_flight_check", {}, ctx=object()))
    assert out == {"ok": True, "mode": "nominal"}
