"""Tests for v4.152.0 Interactive Input Helper."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402

# ---- Registry ----

def test_input_helper_tools_in_registry():
    names = {t["name"] for t in MCP_TOOLS}
    assert "input_helper.health" in names
    assert "input_helper.click" in names
    assert "input_helper.move" in names
    assert "input_helper.type" in names
    assert "input_helper.key" in names
    assert "input_helper.launch" in names
    assert "input_helper.send_chat_command" in names


def test_input_helper_schemas():
    by_name = {t["name"]: t for t in MCP_TOOLS}
    # click requires x, y
    assert "x" in by_name["input_helper.click"]["inputSchema"]["required"]
    assert "y" in by_name["input_helper.click"]["inputSchema"]["required"]
    # type requires text
    assert "text" in by_name["input_helper.type"]["inputSchema"]["required"]
    # key requires name
    assert "name" in by_name["input_helper.key"]["inputSchema"]["required"]
    # launch requires path
    assert "path" in by_name["input_helper.launch"]["inputSchema"]["required"]
    # send_chat_command requires command
    assert "command" in by_name["input_helper.send_chat_command"]["inputSchema"]["required"]
    # health has no required
    assert by_name["input_helper.health"]["inputSchema"].get("additionalProperties") is False


# ---- Client module ----

def test_client_imports():
    from arena.input_helper import client
    assert hasattr(client, "click")
    assert hasattr(client, "move")
    assert hasattr(client, "type_text")
    assert hasattr(client, "key")
    assert hasattr(client, "launch")
    assert hasattr(client, "send_chat_command")
    assert hasattr(client, "is_available")
    assert hasattr(client, "health")


def test_client_is_available_false():
    """When helper is not running, is_available returns False."""
    from arena.input_helper import client
    # Without a running helper, should return False
    assert client.is_available() is False


def test_client_health_error():
    """When helper is not running, health returns error."""
    from arena.input_helper import client
    r = client.health()
    assert r["ok"] is False
    assert "error" in r


# ---- Helper server module imports ----

def test_helper_server_importable():
    """The helper server module should be importable (even on non-Windows)."""
    try:
        from arena.input_helper import helper_server
        assert hasattr(helper_server, "InputHandler")
        assert hasattr(helper_server, "main")
    except ImportError:
        pass  # OK on Linux if ctypes.windll not available


# ---- MCP handler ----

def test_handler_health_returns_error_when_unavailable():
    from arena.mcp.tool_input_helper import handle_input_helper_tool
    result = handle_input_helper_tool("input_helper.health", {}, ctx=None)
    assert result is not None
    content = result.get("content", [{}])
    text = content[0].get("text", "")
    data = json.loads(text)
    assert data["ok"] is False  # helper not running


def test_handler_click_returns_error_when_unavailable():
    from arena.mcp.tool_input_helper import handle_input_helper_tool
    result = handle_input_helper_tool("input_helper.click", {"x": 100, "y": 200}, ctx=None)
    content = result.get("content", [{}])
    text = content[0].get("text", "")
    data = json.loads(text)
    assert data["ok"] is False
    assert "hint" in data  # should suggest starting helper


def test_handler_unknown_returns_none():
    from arena.mcp.tool_input_helper import handle_input_helper_tool
    result = handle_input_helper_tool("input_helper.nonexistent", {}, ctx=None)
    assert result is None


def test_handler_click_missing_coords():
    from arena.mcp.tool_input_helper import handle_input_helper_tool
    result = handle_input_helper_tool("input_helper.click", {}, ctx=None)
    content = result.get("content", [{}])
    text = content[0].get("text", "")
    data = json.loads(text)
    assert data["ok"] is False
    assert "required" in data["error"]
