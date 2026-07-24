"""Tests for the v4.70.0 catalogue-consistency / dispatch-integrity guards.

v4.70.0 ships six new guard scripts in ``scripts/`` plus the
v4.70.0 release commit that added the ``fs.write_base64``
catalogue entry and brought ``handle_mobile_ext_tool``'s
signature into line. This test module exercises the public
behaviour of every new guard so a future refactor can't
silently break one of them.

Each test does one of three things:

* Imports the guard module and calls its ``_run`` function
  on the actual repo. A return code of 0 means the guard
  passed; a non-zero return means the guard caught a real
  violation. The tests assert the expected return code
  (typically 0 for the v4.70.0 baseline).
* Creates a throwaway file in ``arena/mcp/`` (deleted in a
  ``finally`` block) that introduces a known violation, and
  asserts the guard returns 1.
* Sanity-checks the guard's whitelist / known-namespace
  set against the source tree so a renamed function trips
  a clear red X.

The tests run on Linux only — they import the guard
modules directly without spawning a subprocess, so there
is no platform-specific behaviour to test.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


# Locate the repo root from this test file's location.
REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"


def _import_guard(name: str):
    """Import a guard module from scripts/.

    We add ``scripts/`` to ``sys.path`` for the import and
    pop it again immediately so the test session's sys.path
    is not polluted. The guard module is also stashed on
    the test instance so subsequent calls don't re-import.
    """
    sys.path.insert(0, str(SCRIPTS))
    try:
        mod = importlib.import_module(name)
    finally:
        sys.path.pop(0)
    return mod


# -------------------------------------------------------------------
# 1. catalogue_consistency_check
# -------------------------------------------------------------------


def test_catalogue_consistency_passes_on_baseline() -> None:
    guard = _import_guard("catalogue_consistency_check")
    rc = guard._run(REPO)
    assert rc == 0, f"catalogue_consistency_check failed on the v4.70.0 baseline: rc={rc}"


def test_catalogue_consistency_catches_duplicate_name() -> None:
    """Inject a duplicate-name catalogue entry and assert the guard fails.

    We do this by monkey-patching the script's MCP_TOOLS
    import via the ``arena.mcp.tool_registry`` module
    attribute rather than by touching the real registry
    source (which would break every other test in the
    session).
    """
    guard = _import_guard("catalogue_consistency_check")
    sys.path.insert(0, str(REPO))
    try:
        from arena.mcp.tool_registry import MCP_TOOLS as real_tools
    finally:
        sys.path.pop(0)
    fake = list(real_tools) + [dict(real_tools[0])]  # second copy of the first entry
    import arena.mcp.tool_registry as reg
    original = reg.MCP_TOOLS
    reg.MCP_TOOLS = fake
    try:
        rc = guard._run(REPO)
        assert rc == 1, f"expected rc=1 on duplicate name, got {rc}"
    finally:
        reg.MCP_TOOLS = original


# -------------------------------------------------------------------
# 2. dead_dispatch_check
# -------------------------------------------------------------------


def test_dead_dispatch_passes_on_baseline() -> None:
    guard = _import_guard("dead_dispatch_check")
    rc = guard._run(REPO)
    assert rc == 0, f"dead_dispatch_check failed on the v4.70.0 baseline: rc={rc}"


def test_dead_dispatch_catches_dead_reference(tmp_path: Path) -> None:
    """A dispatcher that references a non-existent tool name must fail the guard.

    We add a throwaway ``tool_v4700_tmp.py`` to
    ``arena/mcp/`` that contains a reference to a tool
    name that uses a real namespace (so it passes the
    known-namespace filter) but with an action that is
    NOT in the catalogue. The guard's dead-reference
    branch should fire and return 1.
    """
    guard = _import_guard("dead_dispatch_check")
    target = REPO / "arena" / "mcp" / "tool_v4700_tmp.py"
    if target.exists():
        target.unlink()
    try:
        target.write_text(
            "def handle_v4700_tmp_tool(name, args, *, ctx):\n"
            "    if name == 'fs.v4700_does_not_exist':\n"
            "        return None\n",
            encoding="utf-8",
        )
        rc = guard._run(REPO)
        assert rc == 1, f"expected rc=1 on dead reference, got {rc}"
    finally:
        if target.exists():
            target.unlink()


# -------------------------------------------------------------------
# 3. json_schema_check
# -------------------------------------------------------------------


def test_json_schema_check_passes_on_baseline() -> None:
    guard = _import_guard("json_schema_check")
    rc = guard._run(REPO)
    assert rc == 0, f"json_schema_check failed on the v4.70.0 baseline: rc={rc}"


def test_json_schema_check_catches_unknown_keyword() -> None:
    """Inject a schema with a typo'd keyword and assert the guard fails."""
    guard = _import_guard("json_schema_check")
    sys.path.insert(0, str(REPO))
    try:
        from arena.mcp.tool_registry import MCP_TOOLS as real_tools
    finally:
        sys.path.pop(0)
    fake = list(real_tools) + [
        {
            "name": "v4700.typo_schema",
            "description": "Synthetic test entry with a typo'd keyword.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "addtionalProperties": False,  # typo: should be "additionalProperties"
            },
        }
    ]
    import arena.mcp.tool_registry as reg
    original = reg.MCP_TOOLS
    reg.MCP_TOOLS = fake
    try:
        rc = guard._run(REPO)
        assert rc == 1, f"expected rc=1 on typo'd schema keyword, got {rc}"
    finally:
        reg.MCP_TOOLS = original


def test_json_schema_check_catches_required_but_missing() -> None:
    guard = _import_guard("json_schema_check")
    sys.path.insert(0, str(REPO))
    try:
        from arena.mcp.tool_registry import MCP_TOOLS as real_tools
    finally:
        sys.path.pop(0)
    fake = list(real_tools) + [
        {
            "name": "v4700.required_but_missing",
            "description": "Synthetic test entry with a required field not in properties.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path", "this_does_not_exist"],
            },
        }
    ]
    import arena.mcp.tool_registry as reg
    original = reg.MCP_TOOLS
    reg.MCP_TOOLS = fake
    try:
        rc = guard._run(REPO)
        assert rc == 1, f"expected rc=1 on required-but-missing field, got {rc}"
    finally:
        reg.MCP_TOOLS = original


# -------------------------------------------------------------------
# 4. namespace_doc_coverage (soft-warn by default, --enforce hard)
# -------------------------------------------------------------------


def test_namespace_doc_coverage_warns_by_default() -> None:
    guard = _import_guard("namespace_doc_coverage")
    rc = guard._run(REPO, enforce=False)
    # v4.70.0 baseline: 22 of 23 namespaces lack an example.
    # Soft-warn mode returns 0 (with a report on stderr).
    assert rc == 0, f"soft-warn should return 0; got {rc}"


def test_namespace_doc_coverage_enforce_passes_on_baseline() -> None:
    """v4.72.0 closes the documentation gap: every namespace now has a README example.

    The v4.70.0 baseline had 22 of 23 namespaces
    uncovered, so ``--enforce`` correctly returned 1.
    v4.72.0 adds a per-namespace example table to
    README.md / README.ru.md and promotes the guard to
    ``--enforce`` mode. The new test reflects the new
    baseline: ``--enforce`` now returns 0.
    """
    guard = _import_guard("namespace_doc_coverage")
    rc = guard._run(REPO, enforce=True)
    # v4.72.0 baseline: all 23 namespaces covered, so
    # enforce mode returns 0.
    assert rc == 0, f"enforce mode should return 0 on v4.72.0 baseline; got {rc}"


# -------------------------------------------------------------------
# 5. handler_signature_check
# -------------------------------------------------------------------


def test_handler_signature_passes_on_baseline() -> None:
    guard = _import_guard("handler_signature_check")
    rc = guard._run(REPO)
    assert rc == 0, f"handler_signature_check failed on the v4.70.0 baseline: rc={rc}"


def test_handler_signature_catches_missing_ctx(tmp_path: Path) -> None:
    """A handle_*_tool function without ``*, ctx`` must fail the guard.

    We add a throwaway file with a deliberately bad
    signature and assert the guard returns 1.
    """
    guard = _import_guard("handler_signature_check")
    target = REPO / "arena" / "mcp" / "tool_v4700_tmp.py"
    if target.exists():
        target.unlink()
    try:
        target.write_text(
            "def handle_v4700_tmp_tool(name, args):\n"
            "    return None\n",
            encoding="utf-8",
        )
        rc = guard._run(REPO)
        assert rc == 1, f"expected rc=1 on missing ctx, got {rc}"
    finally:
        if target.exists():
            target.unlink()


# -------------------------------------------------------------------
# 6. handler_namespace_consistency
# -------------------------------------------------------------------


def test_handler_namespace_consistency_passes_on_baseline() -> None:
    """Baseline: shadow-namespace hard fails are 0, soft warns are 1 (mem/memory).

    The guard returns 1 if there are any hard failures, even
    if there are only soft warnings. With the v4.70.0
    follow-up (no shadow-namespace detection triggered),
    only the ``mem.*`` ↔ ``memory.*`` soft warning fires,
    so the overall return code is 0.
    """
    guard = _import_guard("handler_namespace_consistency")
    rc = guard._run(REPO)
    assert rc == 0, f"handler_namespace_consistency failed on baseline: rc={rc}"


def test_handler_namespace_consistency_whitelist_in_sync() -> None:
    """The whitelist of mixed-namespace functions must reference real source.

    A renamed function (or a removed function) would leave
    a stale entry in the whitelist and trip this test
    with a clear message. This is the guard's own
    sanity-check surfaced as a unit test so the failure
    is visible in the test session even if the script
    isn't run.
    """
    guard = _import_guard("handler_namespace_consistency")
    for rel, func_name, _reason in guard._WHITELISTED_MIXED:
        path = REPO / rel
        assert path.is_file(), f"whitelist entry references missing file: {rel}"
        import ast as _ast
        tree = _ast.parse(path.read_text(encoding="utf-8"))
        found = False
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and node.name == func_name:
                found = True
                break
        assert found, f"whitelist entry references missing function: {rel}::{func_name}()"
