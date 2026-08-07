#!/usr/bin/env python3
"""Regenerate tests/_mcp_contract_snapshot.json from the current
``arena/mcp/tool_*.py`` source tree.

Run this locally after a deliberate rename, addition or removal of
an MCP tool, then commit the resulting JSON. The contract test
``test_mcp_tool_contracts.py::test_current_tool_modules_match_snapshot``
will fail until the snapshot is in sync with the source.

The script is intentionally simple — it reuses the same AST scan
the test runs, so there is no risk of the two drifting apart.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL_DIR = REPO / "arena" / "mcp"
SNAPSHOT = REPO / "tests" / "_mcp_contract_snapshot.json"

TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_BAD_EXTS = (
    ".exe", ".dll", ".py", ".json", ".zip", ".sh", ".bat", ".cmd",
    ".vbs", ".txt", ".md", ".log", ".db", ".html", ".css", ".js",
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".tar", ".gz",
    ".mp3", ".mp4", ".wav", ".ogg", ".opus", ".aac", ".m4a",
    ".cpp", ".h", ".hpp", ".rs", ".go", ".ts", ".tsx", ".jsx",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".so",
    ".dylib", ".d", ".o", ".a", ".lib",
)


def _is_tool_name(value: str) -> bool:
    if not TOOL_NAME_RE.match(value):
        return False
    if any(value.endswith(ext) for ext in _BAD_EXTS):
        return False
    left, _, right = value.partition(".")
    return bool(left) and bool(right) and left[0].isalpha() and right[0].isalpha()


def _scan_file(path: Path) -> dict:
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, str(path))
    handlers: list[str] = []
    tool_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("handle_"):
            handlers.append(node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _is_tool_name(node.value):
                tool_names.add(node.value)
    rel = path.relative_to(REPO).as_posix()
    return {
        "file": rel,
        "handlers": sorted(set(handlers)),
        "tool_names": sorted(tool_names),
    }


def main() -> int:
    if not TOOL_DIR.exists():
        print(f"[ERR] {TOOL_DIR} not found; run from the repo root.", file=sys.stderr)
        return 2
    files = sorted(TOOL_DIR.glob("tool_*.py"))
    snapshot = [r for r in (_scan_file(p) for p in files)
                if r["handlers"] or r["tool_names"]]
    snapshot.sort(key=lambda x: x["file"])
    SNAPSHOT.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] wrote {SNAPSHOT.relative_to(REPO)} "
          f"({len(snapshot)} tool modules, "
          f"{sum(len(e['handlers']) for e in snapshot)} handlers, "
          f"{sum(len(e['tool_names']) for e in snapshot)} tool names)")

    # v4.166.0: also refresh the DESCRIPTION fingerprint.
    #
    # Two guards protect the catalogue -- this snapshot (names, handlers,
    # modules) and tests/_mcp_description_fingerprint.json (the prose the
    # model actually reads). The failure message on the second one points
    # here, but this script only ever wrote the first, so following the
    # instructions left the suite red with no further hint. Adding three
    # tools made that obvious; it would have been just as broken for a
    # one-word wording fix.
    return _write_description_fingerprint()


def _write_description_fingerprint() -> int:
    """Record a hash per tool description, so prose edits stay deliberate."""
    import hashlib

    fingerprint_path = REPO / "tests" / "_mcp_description_fingerprint.json"
    try:
        sys.path.insert(0, str(REPO))
        from arena.mcp.tool_registry import MCP_TOOLS
    except Exception as exc:  # noqa: BLE001 -- report, do not half-write
        print(f"[ERR] cannot import the tool registry: {exc}", file=sys.stderr)
        print("      description fingerprint NOT updated", file=sys.stderr)
        return 1

    current = {
        tool["name"]: hashlib.sha256(
            str(tool.get("description") or "").encode("utf-8")).hexdigest()[:16]
        for tool in MCP_TOOLS
    }
    previous = {}
    if fingerprint_path.exists():
        try:
            previous = json.loads(fingerprint_path.read_text(encoding="utf-8"))
        except ValueError:
            previous = {}

    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))
    edited = sorted(n for n in set(current) & set(previous)
                    if current[n] != previous[n])

    fingerprint_path.write_text(
        json.dumps(current, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[OK] wrote {fingerprint_path.relative_to(REPO)} "
          f"({len(current)} descriptions)")
    # Print the diff rather than swallowing it: these strings steer the
    # model, and a silent rewrite is exactly what the guard exists to stop.
    if added:
        print(f"     added:   {', '.join(added)}")
    if removed:
        print(f"     removed: {', '.join(removed)}")
    if edited:
        print(f"     EDITED:  {', '.join(edited)}  <- review these")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
