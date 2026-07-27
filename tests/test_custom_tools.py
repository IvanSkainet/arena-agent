"""Tests for agent-authored custom tools (self-extending environment, v4.96.0)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from arena.extension_bridge.policy import classify_tool_risk
from arena.mcp import custom_tools as ct


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Isolated profile dir so each test starts with no custom tools."""
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    ct._reset_cache()
    yield tmp_path
    ct._reset_cache()


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

def test_normalize_name_adds_prefix():
    assert ct.normalize_name("room_report") == "custom.room_report"
    assert ct.normalize_name("custom.room_report") == "custom.room_report"
    assert ct.normalize_name("") == ""


def test_substitute_exact_token_is_typed():
    out = ct._substitute("{count}", {"count": 5})
    assert out == 5 and isinstance(out, int)


def test_substitute_embedded_token_is_string():
    out = ct._substitute("value is {x}!", {"x": 7})
    assert out == "value is 7!"


def test_substitute_nested_and_passthrough():
    tmpl = {"a": "{x}", "b": ["{y}", 3], "c": True, "d": "lit"}
    out = ct._substitute(tmpl, {"x": "hi", "y": "yo"})
    assert out == {"a": "hi", "b": ["yo", 3], "c": True, "d": "lit"}


def test_validate_schema_rejects_bad_required():
    err = ct.validate_schema({"properties": {"a": {"type": "string"}}, "required": ["b"]})
    assert err and "'b'" in err


def test_validate_schema_rejects_bad_type():
    err = ct.validate_schema({"properties": {"a": {"type": "weird"}}})
    assert err and "unsupported" in err


def test_validate_args_required_and_types():
    spec = {"inputSchema": {"properties": {"n": {"type": "integer"},
                                           "s": {"type": "string"}},
                            "required": ["n"]}}
    assert ct.validate_args(spec, {"n": 1}) is None
    assert "missing required" in ct.validate_args(spec, {})
    assert "type integer" in ct.validate_args(spec, {"n": "x"})


# ---------------------------------------------------------------------------
# CRUD + risk derivation
# ---------------------------------------------------------------------------

def test_create_persists_and_lists(home):
    res = ct.create_tool(
        "echoish", "wrap echo",
        {"properties": {"text": {"type": "string"}}, "required": ["text"]},
        {"tool": "exec.echo", "args": {"text": "{text}"}},
    )
    assert res["ok"], res
    assert res["tool"]["name"] == "custom.echoish"
    # exec.echo is safe-ish (not in any bucket -> unknown -> medium)
    assert res["tool"]["risk"] == "medium"
    names = [t["name"] for t in ct.list_tools()]
    assert "custom.echoish" in names
    # persisted on disk
    raw = json.loads((home / "mcp" / "custom_tools.json").read_text())
    assert "custom.echoish" in raw["tools"]


def test_create_wrapping_safe_tool_inherits_safe(home):
    res = ct.create_tool("reader", "", {"properties": {"path": {"type": "string"}},
                                        "required": ["path"]},
                         {"tool": "fs.read", "args": {"path": "{path}"}})
    assert res["ok"], res
    assert res["tool"]["risk"] == "safe"


def test_create_wrapping_dangerous_tool_inherits_dangerous(home):
    res = ct.create_tool("runner", "", {"properties": {"cmd": {"type": "string"}},
                                        "required": ["cmd"]},
                         {"tool": "exec.exec", "args": {"cmd": "{cmd}"}})
    assert res["ok"], res
    assert res["tool"]["risk"] == "dangerous"


def test_create_rejects_wrapping_custom_tool(home):
    res = ct.create_tool("chain", "", {"properties": {}},
                         {"tool": "custom.other", "args": {}})
    assert not res["ok"] and "built-in" in res["error"]


def test_create_rejects_unknown_wrapped_tool(home):
    res = ct.create_tool("nope", "", {"properties": {}},
                         {"tool": "does.not.exist", "args": {}})
    assert not res["ok"] and "not a known" in res["error"]


def test_custom_namespace_cannot_shadow_builtin(home):
    # The custom. prefix guarantees no collision with built-ins: authoring
    # "custom.fs.read" is allowed and leaves the built-in fs.read untouched.
    res = ct.create_tool("custom.fs.read", "", {"properties": {}},
                         {"tool": "exec.echo", "args": {}})
    assert res["ok"], res
    assert res["tool"]["name"] == "custom.fs.read"
    # the built-in is unaffected and still classifies as its own risk
    assert classify_tool_risk("fs.read") == "safe"


def test_remove(home):
    ct.create_tool("tmp", "", {"properties": {"t": {"type": "string"}}, "required": ["t"]},
                   {"tool": "exec.echo", "args": {"text": "{t}"}})
    assert ct.remove_tool("tmp")["ok"]
    assert ct.get_tool("tmp") is None
    assert not ct.remove_tool("tmp")["ok"]


# ---------------------------------------------------------------------------
# dispatch + risk classification
# ---------------------------------------------------------------------------

def test_handle_invokes_wrapped_via_call_tool(home):
    ct.create_tool("reader", "", {"properties": {"path": {"type": "string"}},
                                  "required": ["path"]},
                   {"tool": "fs.read", "args": {"path": "{path}", "max_bytes": 100}})
    seen = {}

    def fake_call_tool(name, args):
        seen["name"] = name
        seen["args"] = args
        return {"ok": True, "content": [{"type": "text", "text": "DATA"}]}

    out = ct.handle_custom_tool("custom.reader", {"path": "/etc/x"},
                                ctx=SimpleNamespace(call_tool=fake_call_tool))
    assert seen["name"] == "fs.read"
    assert seen["args"] == {"path": "/etc/x", "max_bytes": 100}
    assert out["ok"] is True


def test_handle_validates_args_before_call(home):
    ct.create_tool("reader", "", {"properties": {"path": {"type": "string"}},
                                  "required": ["path"]},
                   {"tool": "fs.read", "args": {"path": "{path}"}})
    called = {"n": 0}

    def fake_call_tool(name, args):
        called["n"] += 1
        return {"ok": True}

    out = ct.handle_custom_tool("custom.reader", {},
                                ctx=SimpleNamespace(call_tool=fake_call_tool))
    assert out["isError"] and called["n"] == 0


def test_handle_management_list_and_unknown(home):
    ctx = SimpleNamespace(call_tool=lambda n, a: None)
    out = ct.handle_custom_tool("custom.list", {}, ctx=ctx)
    parsed = json.loads(out["content"][0]["text"])
    assert parsed["ok"] and parsed["count"] == 0
    # unknown custom.* falls through (None) so the chain can continue
    assert ct.handle_custom_tool("custom.ghost", {}, ctx=ctx) is None
    # non-custom names are ignored
    assert ct.handle_custom_tool("fs.read", {}, ctx=ctx) is None


def test_classify_tool_risk_resolves_custom(home):
    ct.create_tool("reader", "", {"properties": {"p": {"type": "string"}}, "required": ["p"]},
                   {"tool": "fs.read", "args": {"path": "{p}"}})
    ct.create_tool("runner", "", {"properties": {"c": {"type": "string"}}, "required": ["c"]},
                   {"tool": "exec.exec", "args": {"cmd": "{c}"}})
    assert classify_tool_risk("custom.reader") == "safe"
    assert classify_tool_risk("custom.runner") == "dangerous"
    assert classify_tool_risk("custom.list") == "safe"
    assert classify_tool_risk("custom.create") == "medium"
    assert classify_tool_risk("custom.ghost") == "unknown"


def test_tool_defs_are_authored_only(home):
    # tool_defs() returns only the dynamic authored tools; the static
    # management tools (custom.create/list/remove) live in MCP_TOOLS.
    ct.create_tool("reader", "read a file", {"properties": {"p": {"type": "string"}},
                                             "required": ["p"]},
                   {"tool": "fs.read", "args": {"path": "{p}"}})
    names = {d["name"] for d in ct.tool_defs()}
    assert names == {"custom.reader"}


def test_management_tools_registered_in_catalogue():
    from arena.mcp.tool_registry import MCP_TOOLS
    names = {t["name"] for t in MCP_TOOLS}
    assert {"custom.create", "custom.list", "custom.remove"} <= names
