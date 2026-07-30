"""v4.139.0 -- post-update smoke + autostart doctor."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.mcp.tool_service import handle_service_tool  # noqa: E402
from arena.service import autostart_doctor as A  # noqa: E402
from arena.ship import post_update_smoke as P  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_service_tools_registered_and_policy():
    names = {t["name"] for t in MCP_TOOLS}
    assert {"service.autostart_status", "service.autostart_repair"} <= names
    assert classify_tool_risk("service.autostart_status") == "safe"
    assert classify_tool_risk("service.autostart_repair") == "medium"


def test_post_update_smoke_marker_and_status(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    marked = P.mark_pending({"tag": "vX", "reason": "test"})
    assert marked["ok"] is True
    st = P.status()
    assert st["pending"] is True
    assert st["pending_record"]["tag"] == "vX"


def test_post_update_smoke_run_if_pending(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    P.mark_pending({"tag": "vX"})
    class _Smoke:
        @staticmethod
        def run():
            return {"ok": True, "mode": "nominal", "version": "vX", "report_path": "/r", "failed": [], "warnings": []}
    import arena.ship
    monkeypatch.setattr(arena.ship, "smoke", _Smoke, raising=False)
    out = P.run_if_pending()
    assert out["ok"] is True and out["attempted"] is True
    assert P.status()["pending"] is False
    assert P.status()["last"]["smoke"]["mode"] == "nominal"


def test_autostart_status_windows(monkeypatch):
    monkeypatch.setattr(A.platform, "system", lambda: "Windows")
    monkeypatch.setattr(A, "_run", lambda cmd, timeout=15: {"ok": True, "stdout": "<Task><Triggers><LogonTrigger /></Triggers></Task>", "stderr": "", "exit": 0})
    out = A.status()
    assert out["healthy"] is True
    assert out["trigger"] == "logon"


def test_autostart_status_mcp(monkeypatch):
    monkeypatch.setattr(A, "status", lambda: {"ok": True, "healthy": True})
    out = _parsed(handle_service_tool("service.autostart_status", {}, ctx=object()))
    assert out == {"ok": True, "healthy": True}


def test_post_update_smoke_status_state(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    assert P.status()["state"] == "unknown"
    P.mark_pending({"tag": "vY"})
    assert P.status()["state"] == "pending"
    P.last_path().write_text(json.dumps({"ok": False, "attempted": True, "smoke": {"mode": "blocked"}}), encoding="utf-8")
    P.pending_path().unlink()
    assert P.status()["state"] == "failed"
