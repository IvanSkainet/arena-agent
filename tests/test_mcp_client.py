"""v4.94.0 — external MCP client (arena.mcp_client) + mcp.ext_* tools.

Uses a tiny in-process mock MCP server (a Python script speaking JSON-RPC
over stdio) so the client is exercised end-to-end without any real server
or network. Covers: command allowlist, the stdio handshake, tools/list,
tools/call, the manager (config-driven lazy start), and the mcp.ext_*
bridge tools.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_mcp_ext import handle_mcp_ext_tool
from arena.mcp_client import McpClientManager, McpError
from arena.mcp_client.client import _command_allowed


MOCK_SERVER = r'''
import sys, json
def send(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except Exception:
        continue
    m = msg.get("method")
    if m == "initialize":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {
            "protocolVersion": "2025-03-26",
            "serverInfo": {"name": "mock", "version": "0.1"},
            "capabilities": {}}})
    elif m == "tools/list":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [
            {"name": "echo", "description": "echo the arguments back"},
            {"name": "add", "description": "add two numbers"}]}})
    elif m == "tools/call":
        args = msg.get("params", {}).get("arguments", {})
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {
            "content": [{"type": "text", "text": json.dumps(args)}],
            "isError": False}})
    # notifications/initialized has no id -> no response (correct MCP behavior)
'''


@pytest.fixture
def mock_server_path(tmp_path):
    p = tmp_path / "mock_mcp_server.py"
    p.write_text(MOCK_SERVER, encoding="utf-8")
    return p


@pytest.fixture
def manager(tmp_path, mock_server_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {
        "mock": {"command": sys.executable, "args": [str(mock_server_path)]},
    }}), encoding="utf-8")
    mgr = McpClientManager(config_path=cfg)
    yield mgr
    mgr.stop_all()


# --- command allowlist -----------------------------------------------------
def test_command_allowlist():
    assert _command_allowed("npx")
    assert _command_allowed("uvx")
    assert _command_allowed("python3")
    # full paths allowed when the basename is an interpreter
    assert _command_allowed("/x/venv/bin/python")
    assert _command_allowed("C:/x/venv/Scripts/python.exe")
    assert _command_allowed("/usr/local/bin/node")
    # arbitrary binaries rejected
    assert not _command_allowed("rm")
    assert not _command_allowed("/bin/bash")
    assert not _command_allowed("C:/Windows/System32/cmd.exe")


def test_client_refuses_unknown_command():
    from arena.mcp_client.client import McpStdioClient
    with pytest.raises(McpError):
        McpStdioClient("/bin/bash", ["-c", "echo hi"])


# --- stdio client end-to-end (mock server) ---------------------------------
def test_client_handshake_and_list_tools(manager):
    tools = manager.list_tools("mock")
    names = {t["name"] for t in tools}
    assert names == {"echo", "add"}


def test_client_call_tool(manager):
    res = manager.call_tool("mock", "echo", {"hello": "world"})
    assert res["ok"] is True
    text = res["content"][0]["text"]
    assert json.loads(text) == {"hello": "world"}


def test_client_reused_across_calls(manager):
    c1 = manager.get_client("mock")
    manager.call_tool("mock", "echo", {"a": 1})
    c2 = manager.get_client("mock")
    assert c1 is c2  # same persistent process reused


def test_missing_server_errors(manager):
    with pytest.raises(McpError):
        manager.get_client("does-not-exist")


def test_status(manager):
    assert manager.status("mock") == {"registered": True, "running": False}
    manager.get_client("mock")
    assert manager.status("mock") == {"registered": True, "running": True}


# --- mcp.ext_* bridge tools ------------------------------------------------
def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_ext_tools_handler(manager, monkeypatch):
    import arena.mcp.tool_mcp_ext as ext
    monkeypatch.setattr(ext, "get_manager", lambda: manager)
    res = _parsed(handle_mcp_ext_tool("mcp.ext_tools", {"server": "mock"}))
    assert res["ok"] is True
    assert {t["name"] for t in res["tools"]} == {"echo", "add"}


def test_ext_call_handler(manager, monkeypatch):
    import arena.mcp.tool_mcp_ext as ext
    monkeypatch.setattr(ext, "get_manager", lambda: manager)
    res = _parsed(handle_mcp_ext_tool(
        "mcp.ext_call", {"server": "mock", "tool": "echo", "arguments": {"x": 5}}))
    assert res["ok"] is True
    assert json.loads(res["content"][0]["text"]) == {"x": 5}


def test_ext_servers_handler(manager, monkeypatch):
    import arena.mcp.tool_mcp_ext as ext
    monkeypatch.setattr(ext, "get_manager", lambda: manager)
    res = _parsed(handle_mcp_ext_tool("mcp.ext_servers", {}))
    assert res["ok"] is True
    assert res["count"] == 1
    assert res["servers"][0]["name"] == "mock"


def test_ext_call_missing_args():
    res = _parsed(handle_mcp_ext_tool("mcp.ext_call", {"server": "mock"}))
    assert res["ok"] is False


def test_unknown_tool_returns_none():
    assert handle_mcp_ext_tool("mcp.nope", {}) is None
