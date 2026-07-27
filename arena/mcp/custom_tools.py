"""Self-authored tools: the agent grows its own environment (v4.96.0 / v4.98.0).

The bridge ships a fixed set of general tools. This module lets the agent (or
any caller) author a NEW named tool at runtime that becomes a first-class,
callable, persistent, revocable tool -- a capability that did not exist a
moment ago. That is the "dynamic / self-extending environment" rung of the
flight-computer vision.

Two body shapes are supported (a custom tool has exactly one):

* **Single call** (v4.96.0): ``call = {tool, args}`` -- a parameterised call to
  one built-in tool; arguments flow from the custom tool's input schema via
  ``{param}`` substitution.
* **Composition** (v4.98.0): ``steps = [{id, tool, args}, ...]`` -- a pipeline.
  Each step's ``args`` may reference the custom tool's inputs (``{serial}``) and
  any *earlier* step's result via a dotted path (``{steps.<id>.<field>}``). The
  composite returns ``{ok, steps: {id: <result>}, step_ok: {id: bool}}`` so a
  single authored call can gather several readings (e.g. PC + phone state) at
  once. Steps run continue-on-error so one offline source does not hide the
  rest.

There is *no arbitrary code* in either shape: every wrapped/step call recurses
through the normal ``call_tool`` dispatcher, so the same risk policy and the
full agent stop (HALT) apply -- HALT blocks a composite *mid-pipeline* because
each step passes through the chokepoint.

Safety model (the flight-computer bar):
  * A custom tool / step may only use an existing *static* tool -- never another
    custom tool (no recursion / amplification) and never the management tools.
  * Its effective risk is DERIVED: for a single call, from that tool; for a
    composite, the MAX over its steps (the same idea as
    ``scenarios.runtime.derive_scenario_risk``). A composite containing a
    dangerous step is itself dangerous and needs the same approval at the outer
    call; inner steps do not re-prompt (the outer approval is the consent for
    the whole composite, mirroring ``scenario.run``).
  * Creating / removing a capability is a trust decision (``medium``).
  * Storage lives next to ``mcp.json`` (``<home>/mcp/custom_tools.json``).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from arena.mcp.tool_utils import text_content

PREFIX = "custom."
MGMT_CREATE = "custom.create"
MGMT_LIST = "custom.list"
MGMT_REMOVE = "custom.remove"
MGMT_NAMES = {MGMT_CREATE, MGMT_LIST, MGMT_REMOVE}

_JSON_TYPES = {"string", "integer", "number", "boolean", "array", "object"}
# Tokens may carry a dotted path so step results can be referenced.
_TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\}")
_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RISK_ORDER = {"safe": 0, "medium": 1, "dangerous": 2, "unknown": 1}
_RISK_LABEL = {0: "safe", 1: "medium", 2: "dangerous"}
_MISSING = object()

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


def _classify(tool: str) -> str:
    from arena.extension_bridge.policy import classify_tool_risk
    return classify_tool_risk(str(tool or "").strip())


def derived_risk(wrapped_tool: str) -> str:
    """Risk a single-call custom tool inherits from the tool it wraps."""
    risk = _classify(wrapped_tool)
    return "medium" if risk == "unknown" else risk


def _max_risk_label(tools: list[str]) -> str:
    """MAX risk over a list of tools (unknown counts as medium)."""
    mx = max((_RISK_ORDER.get(_classify(t), 1) for t in tools), default=0)
    return _RISK_LABEL[mx]


def derived_risk_spec(spec: dict[str, Any]) -> str:
    """Derived risk for either body shape, recomputed from the tools used."""
    steps = spec.get("steps")
    if isinstance(steps, list) and steps:
        return _max_risk_label([str(s.get("tool", "")) for s in steps])
    return derived_risk((spec.get("call") or {}).get("tool", ""))


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
    # ``steps`` is the namespace for step-result references; an input with that
    # name would shadow it.
    if "steps" in props:
        return "input name 'steps' is reserved (step results live at {steps.<id>})"
    return None


def validate_steps(steps: Any, static: set[str]) -> str | None:
    """Validate a composition pipeline (the ``steps`` body shape)."""
    if not isinstance(steps, list) or not steps:
        return "'steps' must be a non-empty list"
    seen: set[str] = set()
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return f"step #{i} must be an object"
        sid = str(step.get("id", "")).strip()
        if not _ID_RE.match(sid):
            return f"step #{i} has invalid id '{sid}' (use [A-Za-z_][A-Za-z0-9_]*)"
        if sid in seen:
            return f"duplicate step id '{sid}'"
        seen.add(sid)
        tool = str(step.get("tool", "")).strip()
        if not tool:
            return f"step '{sid}' missing 'tool'"
        if tool.startswith(PREFIX) or tool in MGMT_NAMES:
            return (f"step '{sid}' may only use a built-in tool, not a custom/"
                    f"management tool (no recursion)")
        if tool not in static:
            return f"step '{sid}' tool '{tool}' is not a known built-in tool"
        if not isinstance(step.get("args", {}), dict):
            return f"step '{sid}' 'args' must be an object"
    return None


def _resolve(ns: dict[str, Any], path: str) -> Any:
    """Walk a dotted ``path`` against ``ns``; ``_MISSING`` if any hop fails."""
    cur: Any = ns
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return cur


def _substitute(value: Any, ns: dict[str, Any]) -> Any:
    """Fill ``{path}`` tokens from a namespace (inputs + ``steps`` results).

    A value that is *exactly* ``"{path}"`` becomes the raw resolved value (typed;
    ``None`` when the path is absent); tokens embedded in a longer string are
    string-substituted (absent -> empty string). Non-string values pass through.
    """
    if isinstance(value, str):
        m = _TOKEN.fullmatch(value.strip())
        if m:
            r = _resolve(ns, m.group(1))
            return None if r is _MISSING else r

        def repl(match: re.Match[str]) -> str:
            r = _resolve(ns, match.group(1))
            return "" if r is _MISSING else str(r)
        return _TOKEN.sub(repl, value)
    if isinstance(value, list):
        return [_substitute(v, ns) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, ns) for k, v in value.items()}
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
    """Resolve a single-call custom tool to the wrapped (tool, args)."""
    call = spec.get("call") or {}
    wrapped = str(call.get("tool", "")).strip()
    template = call.get("args") or {}
    return wrapped, _substitute(template, dict(args))


def _step_payload(raw: Any) -> tuple[Any, bool]:
    """Parse a call_tool result like execute_sync does; return (data, ok)."""
    text = ""
    is_err = bool(raw.get("isError", False)) if isinstance(raw, dict) else False
    if isinstance(raw, dict):
        parts = list(raw.get("content") or [])
        if parts and isinstance(parts[0], dict):
            text = str(parts[0].get("text", "") or "")
    if text:
        try:
            parsed = json.loads(text)
        except Exception:
            return text, not is_err
        ok = (not is_err) and (parsed.get("ok") is not False
                               if isinstance(parsed, dict) else True)
        return parsed, ok
    return raw, not is_err


def run_steps(spec: dict[str, Any], args: dict[str, Any],
              call_tool) -> dict[str, Any]:
    """Execute a composition pipeline; each step recurses through call_tool.

    Returns an MCP text result carrying ``{ok, steps, step_ok}``. Steps run
    continue-on-error; HALT / policy apply per step because each goes through
    ``call_tool``."""
    steps = spec.get("steps") or []
    ns: dict[str, Any] = dict(args)
    ns["steps"] = {}
    results: dict[str, Any] = {}
    step_ok: dict[str, bool] = {}
    for step in steps:
        sid = str(step.get("id"))
        sargs = _substitute(step.get("args") or {}, ns)
        raw = call_tool(str(step.get("tool")), sargs)
        data, ok = _step_payload(raw)
        results[sid] = data
        step_ok[sid] = ok
        ns["steps"][sid] = data
    return text_content(json.dumps(
        {"ok": all(step_ok.values()), "steps": results, "step_ok": step_ok},
        ensure_ascii=False))


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_tool(name: str, description: str, input_schema: dict[str, Any],
                call: dict[str, Any] | None = None,
                steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Author a new custom tool (single call OR composition)."""
    full = normalize_name(name)
    if not full or full in MGMT_NAMES:
        return {"ok": False, "error": "a tool name (not a reserved name) is required"}
    static = _static_tool_names()
    if full in static:
        return {"ok": False, "error": f"'{full}' collides with a built-in tool"}
    err = validate_schema(input_schema)
    if err:
        return {"ok": False, "error": err}

    has_call = isinstance(call, dict) and bool(str(call.get("tool", "")).strip())
    has_steps = isinstance(steps, list) and len(steps) > 0
    if has_call and has_steps:
        return {"ok": False, "error": "provide either 'call' or 'steps', not both"}
    if not has_call and not has_steps:
        return {"ok": False, "error": "provide 'call' (single) or 'steps' (pipeline)"}

    desc = str(description or "").strip()
    if has_call:
        wrapped = str(call.get("tool", "")).strip()
        if wrapped.startswith(PREFIX) or wrapped in MGMT_NAMES:
            return {"ok": False, "error": (
                "a custom tool may only wrap a built-in tool, not another "
                "custom/management tool")}
        if wrapped not in static:
            return {"ok": False, "error": f"'{wrapped}' is not a known built-in tool"}
        tmpl = call.get("args", {})
        if not isinstance(tmpl, dict):
            return {"ok": False, "error": "'call.args' must be an object"}
        body: dict[str, Any] = {"call": {"tool": wrapped, "args": tmpl}}
        if not desc:
            desc = f"Custom tool wrapping {wrapped}"
    else:
        serr = validate_steps(steps, static)
        if serr:
            return {"ok": False, "error": serr}
        body = {"steps": [{"id": str(s["id"]).strip(),
                           "tool": str(s["tool"]).strip(),
                           "args": s.get("args", {})} for s in steps]}
        if not desc:
            desc = f"Custom composite of {len(steps)} step(s)"

    doc = _load()
    spec = {
        "name": full,
        "description": desc,
        "inputSchema": {
            "type": "object",
            "properties": input_schema.get("properties", {}),
            "required": input_schema.get("required", []),
            "additionalProperties": False,
        },
        **body,
        "risk": derived_risk_spec({**body}),
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
    """MCP tool definitions for the agent-authored tools only."""
    return [spec_to_def(s) for s in list_tools()]


def _body_summary(spec: dict[str, Any]) -> str:
    steps = spec.get("steps")
    if isinstance(steps, list) and steps:
        ids = ", ".join(str(s.get("id")) for s in steps)
        return f"composite of {len(steps)} step(s) [{ids}]"
    return f"wraps {(spec.get('call') or {}).get('tool')}"


def spec_to_def(spec: dict[str, Any]) -> dict[str, Any]:
    risk = spec.get("risk", "medium")
    desc = spec.get("description", "")
    return {
        "name": spec["name"],
        "description": f"{desc} [custom tool, {_body_summary(spec)}; risk: {risk}]",
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
    return derived_risk_spec(spec)  # recompute so it tracks policy changes


def handle_custom_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    """Dispatcher hook. Returns None when ``name`` is not a custom tool."""
    n = str(name or "").strip()
    if not n.startswith(PREFIX):
        return None

    if n == "custom.list":
        return text_content(json.dumps(
            {"ok": True, "count": len(list_tools()), "tools": list_tools()},
            ensure_ascii=False))
    if n == "custom.create":
        res = create_tool(
            str(args.get("name", "") or ""),
            str(args.get("description", "") or ""),
            args.get("input_schema") or args.get("inputSchema") or {},
            call=args.get("call"),
            steps=args.get("steps"),
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
    if isinstance(spec.get("steps"), list) and spec.get("steps"):
        return run_steps(spec, args, ctx.call_tool)
    wrapped, wrapped_args = expand(spec, args)
    return ctx.call_tool(wrapped, wrapped_args)


MGMT_DEFS = [
    {
        "name": MGMT_CREATE,
        "description": (
            "Author a NEW custom tool at runtime -- the agent growing its own "
            "environment. Body is either `call` = {tool, args} (a single "
            "parameterised built-in call) or `steps` = [{id, tool, args}, ...] "
            "(a pipeline whose args may reference inputs as {name} and earlier "
            "step results as {steps.<id>.<field>}; returns {ok, steps, step_ok}). "
            "Arguments flow from `input_schema` via {..} substitution. Risk is "
            "derived (single: from the tool; composite: max over steps), so a "
            "wrapper/composite over a dangerous tool is itself dangerous. Steps "
            "may only use built-in tools (no recursion). Persisted in "
            "mcp/custom_tools.json; appears in tools/list and the Dashboard."
        ),
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string", "description": "tool name (custom. prefix added if absent)"},
            "description": {"type": "string"},
            "input_schema": {"type": "object", "description": "JSON schema: {properties, required}"},
            "call": {"type": "object", "description": "single-call body: {tool, args}"},
            "steps": {"type": "array", "description": "pipeline body: [{id, tool, args}, ...]"},
        }, "required": ["name", "input_schema"], "additionalProperties": False},
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
    "store_path", "normalize_name", "derived_risk", "derived_risk_spec",
    "validate_schema", "validate_steps", "validate_args", "expand", "run_steps",
    "create_tool", "list_tools", "get_tool", "remove_tool", "tool_defs",
    "spec_to_def", "risk_of", "handle_custom_tool",
]
