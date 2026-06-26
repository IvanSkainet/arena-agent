"""Instruction text generation for browser chat extension users."""
from __future__ import annotations

from typing import Any

SAFE_EXAMPLES = [
    ("sys.status", {}),
    ("mission.catalog", {"limit": 5}),
    ("memory.recall", {"q": "project notes", "top": 5}),
    ("browser.read", {"url": "https://example.com"}),
]


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


def extension_instructions(fmt: str = "arena", style: str = "full") -> dict[str, Any]:
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
    return {
        "ok": True,
        "format": fmt,
        "style": style,
        "text": "\n\n".join(parts),
        "examples": examples,
        "safe_tools": [name for name, _args in SAFE_EXAMPLES],
    }


__all__ = ["extension_instructions"]
