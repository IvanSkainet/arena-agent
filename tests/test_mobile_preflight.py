"""v4.135.0 -- Android/POCO mobile preflight."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_mobile_ext import handle_mobile_ext_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.mobile import preflight as P  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_mobile_preflight_tools_registered_and_policy():
    names = {t["name"] for t in MCP_TOOLS}
    assert {"mobile.preflight", "mobile.reconnect", "mobile.observe"} <= names
    assert classify_tool_risk("mobile.preflight") == "safe"
    assert classify_tool_risk("mobile.observe") == "safe"
    assert classify_tool_risk("mobile.reconnect") == "medium"


def test_mobile_preflight_no_adb(monkeypatch):
    monkeypatch.setattr(P, "find_adb", lambda: None)
    monkeypatch.setattr(P, "adb_version", lambda: None)
    monkeypatch.setattr(P, "list_devices", lambda: {"ok": False, "devices": [], "adb_installed": False})
    out = P.preflight()
    assert out["ok"] is False
    assert out["ready"] is False
    assert any(c["name"] == "adb.installed" and not c["ok"] for c in out["checks"])


def test_mobile_preflight_with_device(monkeypatch):
    monkeypatch.setattr(P, "find_adb", lambda: "/adb")
    monkeypatch.setattr(P, "adb_version", lambda: "1.0.41")
    monkeypatch.setattr(P, "list_devices", lambda: {"ok": True, "devices": [{"serial": "s1", "state": "device"}]})
    monkeypatch.setattr(P, "device_info", lambda serial: {"ok": True, "serial": serial, "model": "POCO"})
    monkeypatch.setattr(P._transport, "describe", lambda serial=None: {"ok": True, "devices": []})
    out = P.preflight()
    assert out["ok"] is True
    assert out["ready"] is True
    assert out["selected_serial"] == "s1"
    assert out["info"]["model"] == "POCO"


def test_mobile_observe(monkeypatch):
    monkeypatch.setattr(P, "preflight", lambda serial=None: {"ok": True, "ready": True, "selected_serial": "s1", "info": {"model": "POCO", "android_version": "16"}})
    monkeypatch.setattr(P._ui, "dump_ui", lambda *a, **k: {"ok": True, "nodes": []})
    out = P.observe()
    assert out["ok"] is True
    assert out["ui"]["ok"] is True
    assert out["summary"]["model"] == "POCO"


def test_mobile_preflight_mcp_handler(monkeypatch):
    monkeypatch.setattr(P, "preflight", lambda serial=None: {"ok": True, "serial": serial})
    out = _parsed(handle_mobile_ext_tool("mobile.preflight", {"serial": "s1"}, ctx=object()))
    assert out == {"ok": True, "serial": "s1"}
