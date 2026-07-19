"""Instruction text generation for browser chat extension users.

v4.51.2: full redesign based on studying MCP SuperAssistant
(github.com/srbhptl39/MCP-SuperAssistant/pages/content/src/
components/sidebar/Instructions/).

Two things from MCP SA carried over:
1. **CSN (Compressed Schema Notation)** — collapses JSON Schema
   into a compact one-line notation that saves 3-5x tokens per
   tool description while keeping full expressiveness.
2. **Explicit SYSTEM prompt structure** — clear rules, examples,
   response format, error handling. Prior v4.51.1 catalog just
   dumped raw schemas which the model often ignored.

Original v4.51.1 categories retained (safe/medium/dangerous/all
+ topical). The catalog block now uses CSN + explicit call/wait
protocol rules that AI actually follows.

References:
- MCP SuperAssistant: MIT-licensed; CSN notation adapted;
  system-prompt structure adapted with attribution.
"""
from __future__ import annotations

import json
from typing import Any

from arena.extension_bridge.policy import classify_tool_risk
from arena.mcp.tool_registry import MCP_TOOLS

SAFE_EXAMPLES = [
    ("sys.status", {}),
    ("mission.catalog", {"limit": 5}),
    ("memory.recall", {"q": "project notes", "top": 5}),
    ("browser.read", {"url": "https://example.com"}),
]

# Topical category prefixes.
_CATEGORY_PREFIXES = (
    ("fs", ("fs.",)),
    ("mission", ("mission.",)),
    ("memory", ("memory.", "mem.")),
    ("browser", ("browser.",)),
    ("desktop", ("desktop.",)),
    ("git", ("git.",)),
    ("system", ("sys.", "ping", "echo", "exec", "plan.", "react.",
               "reflect.", "watch.", "hooks.", "snapshot",
               "skill.", "subagent.")),
)

_KNOWN_CATEGORIES = frozenset({
    "all", "safe", "medium", "dangerous",
    "fs", "mission", "memory", "browser", "desktop", "git", "system",
})


def _tool_category(name: str) -> str:
    for cat, prefixes in _CATEGORY_PREFIXES:
        if any(name == p.rstrip(".") or name.startswith(p) for p in prefixes):
            return cat
    return "system"


def _normalize_category(value: str) -> str:
    cat = str(value or "").lower().strip()
    if not cat:
        return "safe"
    if cat not in _KNOWN_CATEGORIES:
        return "safe"
    return cat


def _matches_category(tool: dict[str, Any], category: str) -> bool:
    name = str(tool.get("name", ""))
    if not name:
        return False
    if category == "all":
        return True
    if category in {"safe", "medium", "dangerous"}:
        return classify_tool_risk(name) == category
    return _tool_category(name) == category


# ---------------------------------------------------------------------------
# CSN (Compressed Schema Notation) — adapted from MCP SuperAssistant.
# https://github.com/srbhptl39/MCP-SuperAssistant/blob/main/pages/content/
#   src/components/sidebar/Instructions/schema_converter.ts
# MIT license.
# ---------------------------------------------------------------------------
_TYPE_MAP = {
    "string": "s", "integer": "i", "number": "n",
    "boolean": "b", "array": "a", "object": "o",
    "null": "?",
}


def json_schema_to_csn(schema: Any) -> str:
    """Convert JSON Schema to Compressed Schema Notation.

    Example:
        {"type":"object","properties":{"path":{"type":"string"}},
         "required":["path"],"additionalProperties":false}
    becomes:
        o {p {path:s r} ap f}

    Cuts tool-schema size 3-5x while keeping every constraint the
    AI needs to build a valid call.
    """
    if not isinstance(schema, dict):
        return "any"
    # Enum.
    if schema.get("enum"):
        vals = ", ".join(json.dumps(v) for v in schema["enum"])
        return f"e[{vals}]"
    # Const/literal.
    if "const" in schema:
        return f"lit[{json.dumps(schema['const'])}]"
    # Union (anyOf).
    if isinstance(schema.get("anyOf"), list):
        return "u[" + ", ".join(json_schema_to_csn(s) for s in schema["anyOf"]) + "]"
    # Array.
    if schema.get("type") == "array":
        items = schema.get("items")
        return f"a[{json_schema_to_csn(items) if items else 'any'}]"
    # Object.
    if schema.get("type") == "object":
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        parts = []
        for name, spec in props.items():
            csn = json_schema_to_csn(spec)
            req = " r" if name in required else ""
            dflt = ""
            if isinstance(spec, dict) and "default" in spec:
                dflt = f" d={json.dumps(spec['default'])}"
            parts.append(f"{name}:{csn}{req}{dflt}")
        ap = " ap f" if schema.get("additionalProperties") is False else ""
        body = "; ".join(parts)
        return f"o {{p {{{body}}}{ap}}}"
    # Basic scalar with constraints.
    base = _TYPE_MAP.get(schema.get("type"), schema.get("type") or "any")
    constraints = []
    t = schema.get("type")
    if t == "string":
        if "minLength" in schema: constraints.append(f"minLength={schema['minLength']}")
        if "maxLength" in schema: constraints.append(f"maxLength={schema['maxLength']}")
        if "pattern" in schema: constraints.append(f'pattern="{schema["pattern"]}"')
    elif t in ("number", "integer"):
        if "minimum" in schema: constraints.append(f"min={schema['minimum']}")
        if "maximum" in schema: constraints.append(f"max={schema['maximum']}")
    c = f"({', '.join(constraints)})" if constraints else ""
    d = f" d={json.dumps(schema['default'])}" if "default" in schema else ""
    return f"{base}{c}{d}"


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------
_SYSTEM_PREAMBLE_ARENA = """[Start Fresh Session from here — IMPORTANT]

<SYSTEM>
You are connected to a local Arena Chat Bridge browser extension that can execute tools on the user's machine on your behalf. Your ONLY job when a tool is needed is to emit a correctly-formed tool block and STOP — the extension will capture the block, execute it, and paste the real result back into the conversation for you to continue.

How the Arena bridge works:
1. You emit ONE tool block, correctly fenced, then STOP.
2. The Arena extension detects the block, shows the user a Run button (or auto-runs if the tool is tagged `safe`), then executes the tool locally.
3. The extension pastes the result back into the chat as a follow-up message from the user. Only then do you continue.
4. NEVER fabricate the result yourself. NEVER pretend the tool ran if you did not first emit the block. If you did not emit a valid fenced block, nothing runs.

============================================================
STRICT — Function Call Format (Arena, preferred)
============================================================
Every tool call MUST be wrapped in a fenced code block whose language tag is exactly `arena-tool`. The body of the fence MUST be a single JSON object with these keys:

  { "bridge": "arena",
    "version": 1,
    "calls": [
      { "id": "call_1",
        "tool": "tool.name",
        "arguments": { ... } }
    ] }

Example:

```arena-tool
{
  "bridge": "arena",
  "version": 1,
  "calls": [
    { "id": "call_1", "tool": "sys.status", "arguments": {} }
  ]
}
```

Rules:
- The fence language tag MUST be `arena-tool` (not `json`, not `javascript`, not empty). The extension recognises `arena-tool` first and other tags as fallbacks.
- Emit the fence at the START of the message body, or right after one short explanation paragraph. Do NOT bury it inside prose.
- One tool block per response. Do NOT batch multiple `calls[]` entries unless the user explicitly asks for a batch.
- After the closing ``` STOP. Do not add "here is the result", do not add fake `<function_results>`, do not narrate — just wait.

============================================================
DO NOT — common mistakes to avoid
============================================================
- Do NOT paste the JSON WITHOUT a code fence. A bare `{"bridge":"arena","version":1,"calls":[...]}` in prose is only picked up as a last-resort fallback and the site may strip whitespace inside JSON strings — always wrap in a fence.
- Do NOT wrap the JSON in ```json — some sites render `json` blocks with syntax highlighters that mangle content. Use ```arena-tool.
- Do NOT invent tools that are not listed in the "Available Tools" catalog below. Unknown tools fail with an explicit error.
- Do NOT emit `<function_calls>`, `<invoke>`, `<parameter>` XML tags — that is the MCP SuperAssistant format for other bridges, not Arena. The Arena bridge does not read XML tool calls.
- Do NOT emit multiple tool blocks in one response. If a task needs several calls, do the first, wait for the result, then do the next in your next message.

============================================================
Fallback — MCP-compatible JSONL format
============================================================
On sites where the `arena-tool` fence is aggressively rewritten by the site's own markdown pipeline, you MAY use the MCP SuperAssistant JSONL format instead:

```jsonl
{"type":"function_call_start","name":"sys.status","call_id":"1"}
{"type":"function_call_end","call_id":"1"}
```

Use ONE format per response, not both. Prefer the Arena format whenever possible.

============================================================
CSN notation (used below in tool schemas)
============================================================
  s = string, i = integer, n = number, b = boolean,
  a[t] = array of t,
  o {p {name:type r}} = object with named properties (r = required),
  e[...] = enum, u[t1,t2] = union of types,
  ap f = additionalProperties false,
  d=X = default value X,
  ?t = optional / nullable.

============================================================
Safety rules
============================================================
- Tools tagged (safe) run automatically on trusted sites.
- Tools tagged (medium) or (dangerous) always require the user to click Run — never assume they auto-executed.
- Never emit destructive tools (fs.write, fs.edit, exec, mission.run) without an explicit user request that spells out exactly what to change.
- If a required argument is missing, ASK the user for it in prose. Do NOT guess a path, URL, or command line.

============================================================
Response format
============================================================
1. Optional: one short paragraph explaining what you are about to do and why. Do not describe the tool by its internal name.
2. Exactly ONE ```arena-tool ... ``` fenced block, correctly formed.
3. STOP. Wait for the extension to send back the real result.

</SYSTEM>
"""


def _arena_call_example(tool: str, arguments: dict[str, Any]) -> str:
    payload = {
        "bridge": "arena",
        "version": 1,
        "calls": [{"id": "call_1", "tool": tool, "arguments": arguments}],
    }
    return "```arena-tool\n" + json.dumps(payload, indent=2) + "\n```"


def _jsonl_call_example(tool: str, arguments: dict[str, Any]) -> str:
    lines = [json.dumps({"type": "function_call_start", "name": tool, "call_id": "1"})]
    for key, value in arguments.items():
        lines.append(json.dumps({"type": "parameter", "key": key, "value": value}))
    lines.append(json.dumps({"type": "function_call_end", "call_id": "1"}))
    return "```jsonl\n" + "\n".join(lines) + "\n```"


def _pick_example_args(schema: dict[str, Any]) -> dict[str, Any]:
    """Generate minimal, safe example arguments -- required fields only."""
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    required = schema.get("required", []) if isinstance(schema, dict) else []
    out: dict[str, Any] = {}
    for key in required:
        spec = props.get(key, {}) if isinstance(props, dict) else {}
        t = str(spec.get("type", "string")).lower()
        if t == "integer":
            out[key] = spec.get("default", 1)
        elif t == "number":
            out[key] = spec.get("default", 1.0)
        elif t == "boolean":
            out[key] = spec.get("default", False)
        elif t == "array":
            out[key] = []
        elif t == "object":
            out[key] = {}
        else:
            enum = spec.get("enum")
            if isinstance(enum, list) and enum:
                out[key] = enum[0]
            else:
                out[key] = f"<{key}>"
    return out


def _catalog_entry(tool: dict[str, Any]) -> dict[str, Any]:
    name = str(tool.get("name", ""))
    schema = tool.get("inputSchema", {}) if isinstance(tool.get("inputSchema"), dict) else {}
    args = _pick_example_args(schema)
    return {
        "name": name,
        "risk": classify_tool_risk(name),
        "topic": _tool_category(name),
        "description": str(tool.get("description", "")),
        "input_schema": schema,
        "csn": json_schema_to_csn(schema),
        "example_arguments": args,
    }


def _format_catalog_prompt(entries: list[dict[str, Any]], category: str, fmt: str) -> str:
    """Format a compact catalog with CSN one-liners per tool."""
    lines: list[str] = []
    lines.append(f"## Available Tools — category: {category} ({len(entries)} tool(s))")
    lines.append("")
    lines.append("Each line: `tool.name (risk) — description | schema-csn`")
    lines.append("")
    for entry in entries:
        name = entry["name"]
        risk = entry["risk"]
        desc = (entry["description"] or "").strip().replace("\n", " ")
        csn = entry["csn"]
        lines.append(f"- **{name}** ({risk}) — {desc}")
        lines.append(f"  schema: `{csn}`")
    lines.append("")
    # One worked example (Arena format preferred, or JSONL).
    sample = entries[0] if entries else None
    if sample:
        lines.append("### One worked example")
        if fmt in {"arena", "both"}:
            lines.append(_arena_call_example(sample["name"], sample["example_arguments"]))
        if fmt in {"jsonl", "both"}:
            lines.append(_jsonl_call_example(sample["name"], sample["example_arguments"]))
    return "\n".join(lines).rstrip() + "\n"


def extension_instructions(fmt: str = "arena", style: str = "full",
                           category: str = "") -> dict[str, Any]:
    fmt = str(fmt or "arena").lower().strip()
    if fmt not in {"arena", "jsonl", "both"}:
        fmt = "arena"
    style = "short" if str(style or "full").lower().strip() == "short" else "full"

    catalog: list[dict[str, Any]] = []
    catalog_text = ""
    normalized_category = ""
    parts: list[str] = [_SYSTEM_PREAMBLE_ARENA]

    if category:
        normalized_category = _normalize_category(category)
        catalog = [_catalog_entry(t) for t in MCP_TOOLS if _matches_category(t, normalized_category)]
        catalog.sort(key=lambda e: (e["risk"] == "dangerous", e["risk"] == "medium", e["name"]))
        catalog_text = _format_catalog_prompt(catalog, normalized_category, fmt)
        parts.append(catalog_text)
    else:
        # No catalog requested -- keep the preamble short by
        # showing just the two format examples.
        parts.append("### Example — Arena format")
        parts.append(_arena_call_example(*SAFE_EXAMPLES[0]))
        parts.append("### Example — MCP-compatible JSONL format")
        parts.append(_jsonl_call_example(*SAFE_EXAMPLES[0]))

    examples = {
        "arena": _arena_call_example(*SAFE_EXAMPLES[0]),
        "jsonl": _jsonl_call_example(*SAFE_EXAMPLES[0]),
    }

    return {
        "ok": True,
        "format": fmt,
        "style": style,
        "category": normalized_category,
        "text": "\n\n".join(parts),
        "examples": examples,
        "safe_tools": [name for name, _args in SAFE_EXAMPLES],
        "catalog": catalog,
        "catalog_text": catalog_text,
        "available_categories": sorted(_KNOWN_CATEGORIES),
    }


__all__ = ["extension_instructions", "json_schema_to_csn"]
