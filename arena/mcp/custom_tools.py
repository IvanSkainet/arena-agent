"""Self-authored tools: the agent grows its own environment (v4.96 / v4.98 / v4.99).

The bridge ships a fixed set of general tools. This module lets the agent (or
any caller) author NEW named tools at runtime -- capabilities that did not
exist a moment ago. That is the "dynamic / self-extending environment" rung of
the flight-computer vision. Three body shapes / abilities now exist:

* **Single call** (v4.96): ``call = {tool, args}``.
* **Composition** (v4.98): ``steps = [{id, tool, args}, ...]`` with data flow
  (``{input}`` and ``{steps.<id>.<field>}``); returns ``{ok, steps, step_ok}``.
* **Library / reuse** (v4.99): a step or call may target *another authored
  tool* (``custom.<name>``), so the agent builds reusable abstractions and
  composes them. References must be acyclic and bottom-up (the referenced tool
  must already exist); a recursion-depth cap is the runtime safety net.

There is *no arbitrary code* in any shape: every wrapped/step/nested call
recurses through the normal ``call_tool`` dispatcher, so the same risk policy
and the full agent stop (HALT) apply at *every* level -- HALT blocks a nested
call mid-tree because each hop passes through the chokepoint. A composite's
derived risk is the MAX over its whole reference tree (a chain that touches a
dangerous tool anywhere is itself dangerous and needs approval at the outer
call; inner calls do not re-prompt, mirroring ``scenario.run``).

Storage lives next to ``mcp.json`` (``<home>/mcp/custom_tools.json``).
"""
from __future__ import annotations

import contextvars
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
_TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\}")
_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RISK_ORDER = {"safe": 0, "medium": 1, "dangerous": 2, "unknown": 1}
_RISK_LABEL = {0: "safe", 1: "medium", 2: "dangerous"}
_MISSING = object()

# Runtime safety net for nested custom-tool calls (library reuse). Creation order
# + the cycle check keep the reference graph a DAG, so this only ever trips on a
# pathological/buggy tree; it guarantees termination regardless.
MAX_CUSTOM_DEPTH = 8
_custom_depth: "contextvars.ContextVar[int]" = contextvars.ContextVar(
    "arena_custom_tool_depth", default=0)

_cache: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def store_path() -> Path:
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
    global _cache
    _cache = None


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

def _static_tool_names() -> set[str]:
    from arena.mcp.tool_registry import MCP_TOOLS
    return {str(t.get("name", "")).strip() for t in MCP_TOOLS
            if str(t.get("name", "")).strip()}


def normalize_name(name: str) -> str:
    n = str(name or "").strip()
    if not n:
        return ""
    return n if n.startswith(PREFIX) else PREFIX + n


def _classify(tool: str) -> str:
    from arena.extension_bridge.policy import classify_tool_risk
    return classify_tool_risk(str(tool or "").strip())


def _body_tool_names(spec: dict[str, Any]) -> list[str]:
    steps = spec.get("steps")
    if isinstance(steps, list) and steps:
        return [str(s.get("tool", "")) for s in steps]
    return [str((spec.get("call") or {}).get("tool", ""))]


def _custom_refs(spec: dict[str, Any]) -> list[str]:
    return [t for t in _body_tool_names(spec) if t.startswith(PREFIX)]


def derived_risk_spec(spec: dict[str, Any]) -> str:
    """MAX risk over the whole reference tree (built-ins + nested customs)."""
    return _max_risk_over(_body_tool_names(spec), set())


def _max_risk_over(names: list[str], seen: set[str]) -> str:
    mx = 0
    for t in names:
        t = str(t or "").strip()
        if not t:
            continue
        if t.startswith(PREFIX):
            if t in seen:           # cycle guard (should not happen post-create)
                mx = max(mx, _RISK_ORDER["medium"])
                continue
            sub = _load()["tools"].get(t)
            if not sub:             # dangling reference -> treat as medium
                mx = max(mx, _RISK_ORDER["medium"])
                continue
            rlabel = _max_risk_over(_body_tool_names(sub), seen | {t})
            mx = max(mx, _RISK_ORDER.get(rlabel, 1))
        else:
            mx = max(mx, _RISK_ORDER.get(_classify(t), 1))
    return _RISK_LABEL[mx]


def derived_risk(wrapped_tool: str) -> str:
    risk = _classify(wrapped_tool)
    return "medium" if risk == "unknown" else risk


def validate_schema(schema: Any) -> str | None:
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
    if "steps" in props:
        return "input name 'steps' is reserved (step results live at {steps.<id>})"
    return None


def _check_ref(tool: str, full: str, static: set[str],
               custom_names: set[str]) -> str | None:
    """Validate one referenced tool name (built-in OR existing custom)."""
    if not tool:
        return "missing 'tool'"
    if tool in MGMT_NAMES:
        return f"'{tool}' is a management tool and cannot be referenced"
    if tool == full:
        return "a custom tool cannot reference itself"
    if tool.startswith(PREFIX):
        if tool not in custom_names:
            return (f"custom tool '{tool}' is not defined yet; create it first "
                    f"(library is built bottom-up)")
        return None
    if tool not in static:
        return f"'{tool}' is not a known built-in tool"
    return None


def validate_steps(steps: Any, static: set[str],
                   custom_names: set[str] | None = None,
                   self_name: str | None = None) -> str | None:
    """Structural + reference validation of a composition pipeline."""
    custom_names = custom_names or set()
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
        err = _check_ref(str(step.get("tool", "")).strip(), self_name or "",
                         static, custom_names)
        if err:
            return f"step '{sid}': {err}"
        if not isinstance(step.get("args", {}), dict):
            return f"step '{sid}' 'args' must be an object"
    return None


def _creates_cycle(full: str, ref_custom: list[str]) -> bool:
    """Would adding ``full`` (referencing ``ref_custom``) create a cycle?"""
    graph: dict[str, set[str]] = {full: set(ref_custom)}
    for n, sp in _load()["tools"].items():
        if n == full:
            continue
        graph[n] = set(_custom_refs(sp))
    stack = list(ref_custom)
    visited: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur == full:
            return True
        if cur in visited:
            continue
        visited.add(cur)
        stack.extend(graph.get(cur, ()))
    return False


def _substitute(value: Any, ns: dict[str, Any]) -> Any:
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


def _resolve(ns: dict[str, Any], path: str) -> Any:
    cur: Any = ns
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return cur


def validate_args(spec: dict[str, Any], args: dict[str, Any]) -> str | None:
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
            continue
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
    call = spec.get("call") or {}
    wrapped = str(call.get("tool", "")).strip()
    template = call.get("args") or {}
    return wrapped, _substitute(template, dict(args))


def _step_payload(raw: Any) -> tuple[Any, bool]:
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


def run_steps(spec: dict[str, Any], args: dict[str, Any], call_tool) -> dict[str, Any]:
    steps = spec.get("steps") or []
    ns: dict[str, Any] = dict(args)
    ns["steps"] = {}
    results: dict[str, Any] = {}
    step_ok: dict[str, bool] = {}
    for step in steps:
        sid = str(step.get("id"))
        sargs = _substitute(step.get("args") or {}, ns)
        raw = call_tool(str(step.get("tool")), sargs)  # custom.* recurses via dispatcher
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
    full = normalize_name(name)
    if not full or full in MGMT_NAMES:
        return {"ok": False, "error": "a tool name (not a reserved name) is required"}
    static = _static_tool_names()
    if full in static:
        return {"ok": False, "error": f"'{full}' collides with a built-in tool"}
    err = validate_schema(input_schema)
    if err:
        return {"ok": False, "error": err}

    custom_names = set(_load()["tools"].keys())
    has_call = isinstance(call, dict) and bool(str(call.get("tool", "")).strip())
    has_steps = isinstance(steps, list) and len(steps) > 0
    if has_call and has_steps:
        return {"ok": False, "error": "provide either 'call' or 'steps', not both"}
    if not has_call and not has_steps:
        return {"ok": False, "error": "provide 'call' (single) or 'steps' (pipeline)"}

    desc = str(description or "").strip()
    if has_call:
        # `has_call` is exactly "call is a non-empty mapping"; the check above
        # already returned when neither call nor steps was supplied.
        assert call is not None
        wrapped = str(call.get("tool", "")).strip()
        cerr = _check_ref(wrapped, full, static, custom_names)
        if cerr:
            return {"ok": False, "error": cerr}
        tmpl = call.get("args", {})
        if not isinstance(tmpl, dict):
            return {"ok": False, "error": "'call.args' must be an object"}
        body: dict[str, Any] = {"call": {"tool": wrapped, "args": tmpl}}
        ref_custom = [wrapped] if wrapped.startswith(PREFIX) else []
        if not desc:
            desc = (f"Custom tool wrapping {wrapped}" if not wrapped.startswith(PREFIX)
                    else f"Custom tool reusing {wrapped}")
    else:
        serr = validate_steps(steps, static, custom_names, self_name=full)
        if serr:
            return {"ok": False, "error": serr}
        # validate_steps rejects anything that is not a non-empty list, so the
        # comprehension below cannot meet None.
        assert isinstance(steps, list)
        norm_steps = [{"id": str(s["id"]).strip(),
                       "tool": str(s["tool"]).strip(),
                       "args": s.get("args", {})} for s in steps]
        body = {"steps": norm_steps}
        ref_custom = [s["tool"] for s in norm_steps if s["tool"].startswith(PREFIX)]
        if not desc:
            desc = f"Custom composite of {len(norm_steps)} step(s)"

    if ref_custom and _creates_cycle(full, ref_custom):
        return {"ok": False, "error": (
            "reference cycle detected; the custom-tool library must stay acyclic")}

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
    full = normalize_name(name)
    if full in MGMT_NAMES:
        return "medium" if full != MGMT_LIST else "safe"
    spec = _load()["tools"].get(full)
    if not spec:
        return None
    return derived_risk_spec(spec)


def handle_custom_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
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

    # Recursion-depth safety net for nested custom calls (library reuse).
    depth = _custom_depth.get()
    if depth >= MAX_CUSTOM_DEPTH:
        return {"isError": True, "content": [{
            "type": "text",
            "text": (f"ERROR: custom tool recursion depth exceeded "
                     f"(>{MAX_CUSTOM_DEPTH}); possible reference loop")}] }
    tok = _custom_depth.set(depth + 1)
    try:
        if isinstance(spec.get("steps"), list) and spec.get("steps"):
            return run_steps(spec, args, ctx.call_tool)
        wrapped, wrapped_args = expand(spec, args)
        return ctx.call_tool(wrapped, wrapped_args)
    finally:
        _custom_depth.reset(tok)


MGMT_DEFS = [
    {
        "name": MGMT_CREATE,
        "description": (
            "Author a NEW custom tool at runtime -- the agent growing its own "
            "environment / library. Body is `call` = {tool, args} (single call) "
            "or `steps` = [{id, tool, args}, ...] (pipeline). A step/call's tool "
            "may be a built-in OR another already-defined custom tool "
            "(custom.<name>), so the agent composes reusable abstractions; refs "
            "must be acyclic and bottom-up. Step args reference inputs as {name} "
            "and earlier step results as {steps.<id>.<field>}; a composite "
            "returns {ok, steps, step_ok}. Risk is derived over the whole "
            "reference tree (MAX), so touching a dangerous tool anywhere makes "
            "the composite dangerous. Nested calls recurse through the normal "
            "dispatcher, so HALT and the risk policy apply at every level. "
            "Persisted in mcp/custom_tools.json."
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
    "MAX_CUSTOM_DEPTH", "store_path", "normalize_name", "derived_risk",
    "derived_risk_spec", "validate_schema", "validate_steps", "validate_args",
    "expand", "run_steps", "create_tool", "list_tools", "get_tool",
    "remove_tool", "tool_defs", "spec_to_def", "risk_of", "handle_custom_tool",
]
