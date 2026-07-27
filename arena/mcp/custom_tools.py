"""Self-authored tools: the agent grows its own environment (v4.96.0).

The bridge ships a fixed set of general tools. This module is the first
step toward a *self-extending* environment: the agent (or any caller) can
author a NEW named tool at runtime that becomes a first-class, callable,
persistent, revocable tool — a capability that did not exist a moment ago.

A custom tool is a **named, schema-validated macro over one existing tool
call**. Its body is a parameterised call to a tool the bridge already has;
arguments flow from the custom tool's own input schema into the wrapped
call through ``{param}`` substitution. There is *no arbitrary code*: the
wrapped call still goes through the normal ``call_tool`` dispatcher and
therefore through the same risk policy as anything else.

Safety model (the flight-computer bar):
  * A custom tool may only wrap an existing *static* tool — never another
    custom tool (no recursion chains / amplification) and never the custom
    management tools themselves.
  * Its effective risk is DERIVED from the wrapped tool (the same idea as
    ``scenarios.runtime.derive_scenario_risk``): a custom tool that wraps a
    dangerous tool is itself dangerous and needs the same approval.
  * Creating / removing a capability is a trust decision (``medium``),
    mirroring ``mcp.add`` / ``mcp.remove``.
  * Storage lives next to ``mcp.json`` (``<home>/mcp/custom_tools.json``)
    using the same home resolution as the MCP client.

Public surface:
  * ``create_tool`` / ``list_tools`` / ``get_tool`` / ``remove_tool``
  * ``tool_defs``          -- MCP tool definitions for ``tools/list``.
  * ``handle_custom_tool`` -- dispatcher hook (management + invocation).
  * ``risk_of``            -- derived risk of a ``custom.<name>`` tool.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from arena.mcp.tool_utils import text_content

PREFIX = "custom."
# management tool names (not user-authored; live in the custom.* namespace).
MGMT_CREATE = "custom.create"
MGMT_LIST = "custom.list"
MGMT_REMOVE = "custom.remove"
MGMT_NAMES = {MGMT_CREATE, MGMT_LIST, MGMT_REMOVE}

_JSON_TYPES = {"string", "integer", "number", "boolean", "array", "object"}
_TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

_cache: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def store_path() -> Path:
    """Where custom tools persist: ``<home>/mcp/custom_tools.json``."""
    root = Path(os.environ.get("ARENA_AGENT_HOME",
                               str(Path.home() / "arena-bridge"))).expanduser()
    return root / "mcp" / "custom_tools.json"


def _load() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        data = json.loads(store_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    tools = data.get("tools")
    if not isinstance(tools, dict):
        tools = {}
    _cache = {"tools": tools}
    return _cache


def _save(doc: dict[str, Any]) -> None:
    global _cache
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    _cache = doc


def _reset_cache() -> None:
    """Test hook: drop the in-memory cache so the next load re-reads disk."""
    global _cache
    _cache = None


# ---------------------------------------------------------------------------
# helpers (pure, unit-testable)
# ---------------------------------------------------------------------------

def _static_tool_names() -> set[str]:
    """Names of the bridge's built-in (static) tools."""
    from arena.mcp.tool_registry import MCP_TOOLS
    return {str(t.get("name", "")).strip() for t in MCP_TOOLS
            if str(t.get("name", "")).strip()}


def normalize_name(name: str) -> str:
    """Ensure a custom tool name carries the ``custom.`` prefix."""
    n = str(name or "").strip()
    if not n:
        return ""
    return n if n.startswith(PREFIX) else PREFIX + n


def derived_risk(wrapped_tool: str) -> str:
    """Risk a custom tool inherits from the tool it wraps."""
    from arena.extension_bridge.policy import classify_tool_risk
    risk = classify_tool_risk(str(wrapped_tool or "").strip())
    # An unclassifiable wrapped tool still requires approval (treat as medium).
    return "medium" if risk == "unknown" else risk


def validate_schema(schema: Any) -> str | None:
    """Return an error string if ``schema`` is not a usable input schema."""
    if not isinstance(schema, dict):
        return "input_schema must be an object"
    props = schema.get("properties", {})
    if not isinstance(props, dict):
        return "input_schema.properties must be an object"
    for pname, pdef in props.items():
        if not isinstance(pdef, dict):
            return f"input_schema.properties.{pname} must be an object"
        ptype = pdef.get("type", "string")
        if ptype not in _JSON_TYPES:
            return f"input_schema.properties.{pname}.type '{ptype}' unsupported"
    req = schema.get("required", [])
    if not isinstance(req, list):
        return "input_schema.required must be a list"
    for r in req:
        if r not in props:
            return f"required field '{r}' missing from properties"
    return None


def _substitute(value: Any, args: dict[str, Any]) -> Any:
    """Fill ``{param}`` tokens in a call-template value from ``args``.

    A value that is *exactly* ``"{param}"`` becomes the raw (typed) argument;
    tokens embedded in a longer string are string-substituted. Non-string
    values pass through unchanged."""
    if isinstance(value, str):
        m = _TOKEN.fullmatch(value.strip())
        if m:
            key = m.group(1)
            return args.get(key)
        def repl(match: re.Match[str]) -> str:
            return str(args.get(match.group(1), ""))
        return _TOKEN.sub(repl, value)
    if isinstance(value, list):
        return [_substitute(v, args) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, args) for k, v in value.items()}
    return value


def validate_args(spec: dict[str, Any], args: dict[str, Any]) -> str | None:
    """Light JSON-schema validation: required present + basic type check."""
    schema = spec.get("inputSchema") or {}
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    required = schema.get("required", []) if isinstance(schema, dict) else []
    if not isinstance(args, dict):
        return "arguments must be an object"
    for r in required:
        if r not in args:
            return f"missing required argument '{r}'"
    for key, val in args.items():
        pdef = props.get(key)
        if not isinstance(pdef, dict):
            continue  # extra args are tolerated (forward-compat)
        ptype = pdef.get("type", "string")
        if not _type_ok(ptype, val):
            return f"argument '{key}' must be of type {ptype}"
    return None


def _type_ok(ptype: str, val: Any) -> bool:
    if ptype == "string":
        return isinstance(val, str)
    if ptype == "integer":
        return isinstance(val, int) and not isinstance(val, bool)
    if ptype == "number":
        return isinstance(val, (int, float)) and not isinstance(val, bool)
    if ptype == "boolean":
        return isinstance(val, bool)
    if ptype == "array":
        return isinstance(val, list)
    if ptype == "object":
        return isinstance(val, dict)
    return True


def expand(spec: dict[str, Any], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Resolve a custom tool invocation to the wrapped (tool, args)."""
    call = spec.get("call") or {}
    wrapped = str(call.get("tool", "")).strip()
    template = call.get("args") or {}
    return wrapped, _substitute(template, args)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_tool(name: str, description: str, input_schema: dict[str, Any],
                call: dict[str, Any]) -> dict[str, Any]:
    """Author a new custom tool. Returns ``{ok, tool}`` or ``{ok:False,error}``."""
    full = normalize_name(name)
    if not full or full in MGMT_NAMES:
        return {"ok": False, "error": "a tool name (not a reserved name) is required"}
    if full in {MGMT_CREATE, MGMT_LIST, MGMT_REMOVE}:
        return {"ok": False, "error": f"'{full}' is reserved"}
    static = _static_tool_names()
    if full in static:
        return {"ok": False, "error": f"'{full}' collides with a built-in tool"}
    err = validate_schema(input_schema)
    if err:
        return {"ok": False, "error": err}
    if not isinstance(call, dict):
        return {"ok": False, "error": "'call' must be an object"}
    wrapped = str(call.get("tool", "")).strip()
    if not wrapped:
        return {"ok": False, "error": "'call.tool' is required"}
    if wrapped.startswith(PREFIX):
        return {"ok": False, "error": (
            "a custom tool may only wrap a built-in tool, not another "
            "custom tool (no composition chains in v4.96.0)")}
    if wrapped not in static:
        return {"ok": False, "error": f"'{wrapped}' is not a known built-in tool"}
    tmpl = call.get("args", {})
    if not isinstance(tmpl, dict):
        return {"ok": False, "error": "'call.args' must be an object"}

    doc = _load()
    spec = {
        "name": full,
        "description": str(description or "").strip() or f"Custom tool wrapping {wrapped}",
        "inputSchema": {
            "type": "object",
            "properties": input_schema.get("properties", {}),
            "required": input_schema.get("required", []),
            "additionalProperties": False,
        },
        "call": {"tool": wrapped, "args": tmpl},
        "risk": derived_risk(wrapped),
    }
    doc["tools"][full] = spec
    _save(doc)
    return {"ok": True, "tool": spec}


def list_tools() -> list[dict[str, Any]]:
    doc = _load()
    return [doc["tools"][k] for k in sorted(doc["tools"])]


def get_tool(name: str) -> dict[str, Any] | None:
    full = normalize_name(name)
    return _load()["tools"].get(full)


def remove_tool(name: str) -> dict[str, Any]:
    full = normalize_name(name)
    doc = _load()
    if full not in doc["tools"]:
        return {"ok": False, "error": f"'{full}' is not a custom tool"}
    del doc["tools"][full]
    _save(doc)
    return {"ok": True, "removed": full}


# ---------------------------------------------------------------------------
# MCP surface
# ---------------------------------------------------------------------------

def tool_defs() -> list[dict[str, Any]]:
    """MCP tool definitions for the agent-authored tools only.

    The management tools (custom.create/list/remove) are static and live in
    the main ``MCP_TOOLS`` registry; this returns just the dynamic, authored
    ones so ``tools/list`` can append them."""
    return [spec_to_def(s) for s in list_tools()]


def spec_to_def(spec: dict[str, Any]) -> dict[str, Any]:
    risk = spec.get("risk", "medium")
    desc = spec.get("description", "")
    return {
        "name": spec["name"],
        "description": f"{desc} [custom tool, wraps {spec['call']['tool']}; risk: {risk}]",
        "inputSchema": spec.get("inputSchema", {"type": "object", "properties": {}}),
    }


def risk_of(name: str) -> str | None:
    """Derived risk of an authored ``custom.<name>`` tool (None if unknown)."""
    full = normalize_name(name)
    if full in MGMT_NAMES:
        return "medium" if full != MGMT_LIST else "safe"
    spec = _load()["tools"].get(full)
    if not spec:
        return None
    # recompute from the wrapped tool so it tracks policy changes.
    return derived_risk(spec["call"]["tool"])


def handle_custom_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    """Dispatcher hook. Returns None when ``name`` is not a custom tool.

    Mirrors ``handle_scenario_tool``: the dispatcher passes a ctx carrying
    ``call_tool`` so an authored tool's wrapped call recurses through the
    normal tool bus (keeping the wrapped tool's own policy/risk handling)."""
    n = str(name or "").strip()
    if not n.startswith(PREFIX):
        return None

    # The management tool names appear as literals here (not just via the
    # MGMT_* constants) so the dispatch-consistency guards can see that the
    # ``custom`` namespace is handled by this function.
    if n == "custom.list":
        return text_content(json.dumps(
            {"ok": True, "count": len(list_tools()), "tools": list_tools()},
            ensure_ascii=False))
    if n == "custom.create":
        res = create_tool(
            str(args.get("name", "") or ""),
            str(args.get("description", "") or ""),
            args.get("input_schema") or args.get("inputSchema") or {},
            args.get("call") or {},
        )
        return text_content(json.dumps(res, ensure_ascii=False))
    if n == "custom.remove":
        res = remove_tool(str(args.get("name", "") or ""))
        return text_content(json.dumps(res, ensure_ascii=False))

    spec = get_tool(n)
    if spec is None:
        return None  # unknown custom.* name -> let the chain fall through
    err = validate_args(spec, args)
    if err:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {err}"}]}
    wrapped, wrapped_args = expand(spec, args)
    # Recurse through the normal dispatcher so the wrapped call keeps its
    # own policy/risk handling. (Composition chains are disallowed at create
    # time, so this cannot loop back into another custom tool.)
    return ctx.call_tool(wrapped, wrapped_args)


MGMT_DEFS = [
    {
        "name": MGMT_CREATE,
        "description": (
            "Author a NEW custom tool at runtime — the agent growing its own "
            "environment. A custom tool is a named, schema-validated wrapper "
            "around ONE built-in tool call: arguments flow from `input_schema` "
            "into `call.args` via {param} substitution. Its risk is derived "
            "from the wrapped tool (a wrapper over a dangerous tool is itself "
            "dangerous). It may not wrap another custom tool. Persisted in "
            "mcp/custom_tools.json; appears in tools/list and the Dashboard."
        ),
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string", "description": "tool name (custom. prefix added if absent)"},
            "description": {"type": "string"},
            "input_schema": {"type": "object", "description": "JSON schema: {properties, required}"},
            "call": {"type": "object", "description": "{tool: <built-in tool>, args: {param-template}}"},
        }, "required": ["name", "input_schema", "call"], "additionalProperties": False},
    },
    {
        "name": MGMT_LIST,
        "description": "List agent-authored custom tools.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": MGMT_REMOVE,
        "description": "Remove an agent-authored custom tool (revocable capability).",
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string"},
        }, "required": ["name"], "additionalProperties": False},
    },
]


__all__ = [
    "PREFIX", "MGMT_CREATE", "MGMT_LIST", "MGMT_REMOVE", "MGMT_NAMES",
    "store_path", "normalize_name", "derived_risk", "validate_schema",
    "validate_args", "expand", "create_tool", "list_tools", "get_tool",
    "remove_tool", "tool_defs", "spec_to_def", "risk_of", "handle_custom_tool",
]
