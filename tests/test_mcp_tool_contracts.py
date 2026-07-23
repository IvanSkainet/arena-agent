"""v4.61.0 - contract tests for MCP tools.

A refactor that renames ``handle_fs_tool`` to ``handle_filesystem_tool``,
or accidentally drops ``fs.write_base64`` from the dispatch, must be
caught before it lands on master. Without this test, a silent rename
breaks every scenario that referenced the old name and the failure
only surfaces when a user runs the scenario.

Strategy: scan every ``arena/mcp/tool_*.py`` file via the AST, find
``handle_*`` functions and string literals that look like MCP tool
names (format ``prefix.suffix``, both alphabetic-leading), and compare
the result against a checked-in JSON snapshot at
``tests/_mcp_contract_snapshot.json``.

If a tool name is added, removed, or renamed, the snapshot diff fails
and the operator updates the snapshot deliberately (not silently).

The test does not import the modules under test — that would require
the full bridge runtime (network, filesystem, secret store, etc.) and
would couple the contract test to infrastructure. The AST scan is
enough to catch the class of bugs we care about: signature drift,
dispatch-table rot, accidental deletions.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Iterable

import pytest


REPO = Path(__file__).resolve().parent.parent
TOOL_DIR = REPO / "arena" / "mcp"
SNAPSHOT = REPO / "tests" / "_mcp_contract_snapshot.json"

# When this file lives in /home/user/v6020_audit/tests/, parents[1]
# is the v6020_audit scratch root, which mirrors the real repo layout
# (arena/, scripts/, tests/).  When it lives in a real repo's tests/
# dir, parents[1] is the repo root. Both work the same way.
#

# Match identifiers that look like MCP tool names. Strict on purpose:
#   * must start with a letter
#   * dots separate the namespace from the action
#   * no path separators, no file extensions, no spaces
TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

# File extensions we explicitly reject so we don't pick up
# "chrome.exe", "whisper.cpp", "memory.db" etc. as tool names.
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
    """Return a {handlers, tool_names} dict for one tool module."""
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
    return {
        "file": str(path.relative_to(REPO)),
        "handlers": sorted(set(handlers)),
        "tool_names": sorted(tool_names),
    }


def _scan_all() -> list[dict]:
    if not TOOL_DIR.exists():
        pytest.skip(f"tool dir {TOOL_DIR} not present (running outside the repo)")
    files = sorted(TOOL_DIR.glob("tool_*.py"))
    out = [r for r in (_scan_file(p) for p in files) if r["handlers"] or r["tool_names"]]
    return out


# ---------------------------------------------------------------------------
# Snapshot tests
# ---------------------------------------------------------------------------


def test_snapshot_file_exists() -> None:
    assert SNAPSHOT.exists(), (
        f"{SNAPSHOT.name} is missing. Run this test once with --update-snapshot "
        "to bootstrap it, then commit the result."
    )


def test_snapshot_is_sorted_and_unique() -> None:
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    files = [entry["file"] for entry in data]
    assert files == sorted(files), "snapshot is not sorted by file"
    assert len(files) == len(set(files)), "snapshot has duplicate file entries"
    for entry in data:
        assert entry["handlers"] == sorted(entry["handlers"]), \
            f"{entry['file']}: handlers not sorted"
        assert entry["tool_names"] == sorted(entry["tool_names"]), \
            f"{entry['file']}: tool_names not sorted"
        # No duplicate tool names within a single entry.
        assert len(entry["tool_names"]) == len(set(entry["tool_names"]))


def test_current_tool_modules_match_snapshot() -> None:
    """The hard contract: every ``arena/mcp/tool_*.py`` must produce
    the same set of handlers + tool names as the checked-in snapshot.

    If a developer adds, removes, or renames a tool, this test fails
    with a clear diff. The fix is to update the snapshot deliberately
    (and review the diff in the PR).
    """
    if not SNAPSHOT.exists():
        pytest.skip("no snapshot yet; bootstrap with --update-snapshot")
    actual = _scan_all()
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if actual != expected:
        # Render a human-readable diff so a CI log makes the breakage obvious.
        actual_set = {(e["file"], tuple(e["handlers"]), tuple(e["tool_names"]))
                      for e in actual}
        expected_set = {(e["file"], tuple(e["handlers"]), tuple(e["tool_names"]))
                        for e in expected}
        added = sorted(actual_set - expected_set)
        removed = sorted(expected_set - actual_set)
        msg = ["MCP tool contract changed."]
        for file_, handlers, tools in added:
            msg.append(f"  + {file_}: handlers={list(handlers)} tool_names={list(tools)}")
        for file_, handlers, tools in removed:
            msg.append(f"  - {file_}: handlers={list(handlers)} tool_names={list(tools)}")
        msg.append(
            "\nIf this change is intentional, regenerate the snapshot with:\n"
            "  python scripts/refresh_mcp_contract_snapshot.py"
        )
        pytest.fail("\n".join(msg))


def test_no_duplicate_tool_names_across_handler_modules() -> None:
    """A tool name is registered exactly once across handler modules.
    Duplicates almost always mean a copy-paste from one handler to
    another forgot to update the namespace.

    Registry modules (``tool_registry*.py``) intentionally re-list
    every tool name for central dispatch -- that's by design, so we
    exclude them from this check.
    """
    data = _scan_all()
    # Restrict the check to handler modules: those that have at least
    # one handle_* function. Registry modules have tool names but no
    # handlers.
    handler_modules = [e for e in data if e["handlers"]]
    seen: dict[str, str] = {}
    dupes: list[tuple[str, str, str]] = []
    for entry in handler_modules:
        for tn in entry["tool_names"]:
            if tn in seen and seen[tn] != entry["file"]:
                dupes.append((tn, seen[tn], entry["file"]))
            else:
                seen[tn] = entry["file"]
    assert not dupes, (
        "duplicate tool names across handler modules: " +
        "; ".join(f"{tn!r} in {a} and {b}" for tn, a, b in dupes)
    )


# v4.61.0: tool_exec.py hosts the legacy pre-MCP tools (ping, echo,
# exec) whose names do not follow the namespace.action convention.
# They are dispatched by handle_exec_tool but their tool names are
# bare identifiers, so the dot-style "every handler must have tool
# names" check would falsely fire. v4.62.x will normalise them to
# exec.ping / exec.echo / exec.exec and this list can shrink.
_LEGACY_HANDLER_MODULES = frozenset({"arena/mcp/tool_exec.py"})


def test_every_handler_function_is_in_a_module_with_tool_names() -> None:
    """A ``handle_*`` function that does NOT have any tool-name string
    literals in its module is suspicious -- either the handler is
    dead code, or its dispatch table is in a constants file (e.g.
    ``tool_registry.py``) that we should also cover.

    The exception is ``tool_exec.py``, which dispatches legacy
    pre-MCP tools with bare names (``ping``, ``echo``, ``exec``)
    rather than the standard ``namespace.action`` format. We do
    not enforce the convention there in v4.61.0.
    """
    data = _scan_all()
    for entry in data:
        if entry["file"] in _LEGACY_HANDLER_MODULES:
            continue
        if entry["handlers"] and not entry["tool_names"]:
            pytest.fail(
                f"{entry['file']} declares handler(s) {entry['handlers']!r} "
                "but has no tool-name literals; dispatch is likely broken."
            )


def test_all_tool_names_use_snake_case_namespace() -> None:
    """One last style gate: namespace and action must both be lower
    snake_case (no CamelCase, no digits-only segments, no mixed case).
    This is enforced by the regex above but worth re-asserting with a
    friendlier failure message."""
    data = _scan_all()
    style = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    for entry in data:
        for tn in entry["tool_names"]:
            assert style.match(tn), (
                f"{entry['file']}: tool name {tn!r} violates snake.case "
                "namespace.action format"
            )
