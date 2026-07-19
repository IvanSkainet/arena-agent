"""Instruction text generation for browser chat extension users.

v4.51.1: extended with a full tool catalog per category. When
``category`` is passed the returned ``text`` becomes a
self-contained prompt block that enumerates every tool in that
category with its argument schema and one worked example so an
AI can compose calls without needing to search the docs first.

Categories: ``all``, ``safe``, ``medium``, ``dangerous`` (from
policy.py risk buckets) and topical: ``fs``, ``mission``,
``memory``, ``browser``, ``desktop``, ``git``, ``system``.
Unknown values fall back to ``safe`` (the least-risky default).

MCP SuperAssistant compatibility: the JSONL format is unchanged
from v0.14.0, only the surrounding prompt catalog is new.
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

# Topical category prefixes. Order matters: first match wins so
# `mission.schedule_state` goes to `mission`, not `system`.
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

# The top set of categories the popup / catalog UI exposes.
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


def _pick_example_args(schema: dict[str, Any]) -> dict[str, Any]:
    """Generate a minimal, safe example arguments dict from an
    inputSchema. Only fills required fields with clearly-marked
    placeholder values -- never guesses a real path/URL/query."""
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
        "example_arguments": args,
    }


def _format_catalog_prompt(entries: list[dict[str, Any]], category: str) -> str:
    lines: list[str] = []
    lines.append(f"# Arena tool catalog — category: {category}")
    lines.append(f"# {len(entries)} tools listed. Every entry shows risk, description,")
    lines.append("# required argument names, and one example call in Arena tool format.")
    lines.append("")
    for entry in entries:
        name = entry["name"]
        risk = entry["risk"]
        desc = entry["description"] or "(no description)"
        schema = entry["input_schema"]
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        required = schema.get("required", []) if isinstance(schema, dict) else []
        lines.append(f"## {name}  ({risk})")
        lines.append(desc)
        if props:
            arg_summaries: list[str] = []
            for key, spec in props.items():
                t = spec.get("type", "string") if isinstance(spec, dict) else "string"
                marker = "*" if key in required else ""
                arg_summaries.append(f"{key}{marker}:{t}")
            lines.append("Arguments (`*` = required): " + ", ".join(arg_summaries))
        else:
            lines.append("Arguments: none.")
        example_call = {
            "bridge": "arena",
            "version": 1,
            "calls": [{"id": "call_1", "tool": name, "arguments": entry["example_arguments"]}],
        }
        lines.append("Example:")
        lines.append("```arena-tool")
        lines.append(json.dumps(example_call, indent=2))
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _arena_block(tool: str, arguments: dict[str, Any]) -> str:
    return (
        "```arena-tool\n"
        "{\n"
        '  "bridge": "arena",\n'
        '  "version": 1,\n'
        '  "calls": [\n'
        "    {\n"
        '      "id": "call_1",\n'
        f'      "tool": "{tool}",\n'
        f'      "arguments": {arguments!r}\n'.replace("'", '"') +
        "    }\n"
        "  ]\n"
        "}\n"
        "```"
    )


def _jsonl_block(tool: str, arguments: dict[str, Any]) -> str:
    lines = [f'{{"type":"function_call_start","name":"{tool}","call_id":"1"}}']
    for key, value in arguments.items():
        raw = str(value).replace('"', '\\"')
        lines.append(f'{{"type":"parameter","key":"{key}","value":"{raw}"}}')
    lines.append('{"type":"function_call_end","call_id":"1"}')
    return "```jsonl\n" + "\n".join(lines) + "\n```"


def extension_instructions(fmt: str = "arena", style: str = "full",
                           category: str = "") -> dict[str, Any]:
    fmt = str(fmt or "arena").lower().strip()
    if fmt not in {"arena", "jsonl", "both"}:
        fmt = "arena"
    style = "short" if str(style or "full").lower().strip() == "short" else "full"
    examples = {
        "arena": _arena_block(*SAFE_EXAMPLES[0]),
        "jsonl": _jsonl_block(*SAFE_EXAMPLES[0]),
    }
    parts = [
        "You can request local tool execution through the Arena Chat Bridge browser extension.",
        "Only emit a tool block when you need the local Arena bridge to run a tool.",
        "After emitting a tool block, stop and wait for the user/extension to provide the result. Do not invent tool results.",
        "Prefer safe/read-only tools unless the user explicitly asks for a changing or dangerous action.",
    ]
    if style == "full":
        parts.extend([
            "Useful safe tools include sys.status, mission.catalog, mission.lineage, mission.family, mission.history, memory.recall, browser.read, browser.search, fs.view, and fs.grep.",
            "Risky tools such as exec, fs.write, fs.edit, mission.run, mission.iterate, desktop.*, skill.run, and subagent.spawn require explicit user approval.",
            "Every call must include a tool name and an arguments object. Use one block for a batch of related calls.",
        ])
    if fmt in {"arena", "both"}:
        parts.extend(["Preferred Arena format:", examples["arena"]])
    if fmt in {"jsonl", "both"}:
        parts.extend(["MCP SuperAssistant-compatible JSONL format:", examples["jsonl"]])

    catalog: list[dict[str, Any]] = []
    catalog_text = ""
    normalized_category = ""
    if category:
        # Only build the catalog when the caller explicitly asked
        # for one. Empty string preserves the v0.14.0 behaviour.
        normalized_category = _normalize_category(category)
        catalog = [_catalog_entry(t) for t in MCP_TOOLS if _matches_category(t, normalized_category)]
        catalog.sort(key=lambda e: (e["risk"] == "dangerous", e["risk"] == "medium", e["name"]))
        catalog_text = _format_catalog_prompt(catalog, normalized_category)
        parts.append(catalog_text)

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


__all__ = ["extension_instructions"]
