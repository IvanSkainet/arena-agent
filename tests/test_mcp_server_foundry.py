"""v4.133.0 -- MCP Server Foundry."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena import mcp_server_foundry as F  # noqa: E402
from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_mcp_server_foundry import handle_mcp_server_foundry_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_mcp_server_foundry_tools_registered_and_policy():
    names = {t["name"] for t in MCP_TOOLS}
    assert {"mcp_server.create", "mcp_server.list", "mcp_server.test", "mcp_server.install"} <= names
    assert classify_tool_risk("mcp_server.list") == "safe"
    assert classify_tool_risk("mcp_server.test") == "safe"
    assert classify_tool_risk("mcp_server.create") == "medium"
    assert classify_tool_risk("mcp_server.install") == "medium"


def test_mcp_server_create_default_and_test(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    out = F.create("demo", overwrite=True)
    assert out["ok"] is True
    assert (tmp_path / "mcp-servers" / "demo" / "server.py").exists()
    tested = F.test("demo", tool="echo", arguments={"text": "hi"})
    assert tested["ok"] is True, tested
    assert tested["tool_count"] == 1
    assert tested["call"]["ok"] is True
    assert "MCP_SERVER_FOUNDRY_PROOF" in tested["call"]["content"][0]["text"]


def test_mcp_server_install_writes_mcp_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    F.create("demo", overwrite=True)
    out = F.install("demo", force=True, test_tool="echo", test_arguments={"text": "install"})
    assert out["ok"] is True, out
    cfg = json.loads((tmp_path / "mcp" / "mcp.json").read_text(encoding="utf-8"))
    assert "demo" in cfg["mcpServers"]
    assert cfg["mcpServers"]["demo"]["cwd"].endswith("demo")


def test_mcp_server_mcp_handlers(monkeypatch):
    monkeypatch.setattr(F, "list_servers", lambda: {"ok": True, "count": 0})
    out = _parsed(handle_mcp_server_foundry_tool("mcp_server.list", {}, ctx=object()))
    assert out == {"ok": True, "count": 0}
