"""Tests for the v4.72.0 namespace documentation coverage promotion.

v4.70.0 shipped ``scripts/namespace_doc_coverage.py`` in
soft-warn mode (the baseline had 22 of 23 namespaces
lacking README examples). v4.72.0 closes the
documentation gap by adding a per-namespace example
table to ``README.md`` / ``README.ru.md`` and promotes
the guard to ``--enforce`` mode in CI so any future
namespace added without a README example trips a red X
at PR time.

This test module pins the new behaviour:

1. The current repo's README covers all 23 namespaces
   (the v4.72.0 baseline — what we just wrote).
2. The script exits 0 in ``--enforce`` mode on the
   current repo.
3. If a new namespace is added to ``MCP_TOOLS`` without
   a corresponding README example, the script exits 1 in
   ``--enforce`` mode.

The test is intentionally simple: it imports the guard
module directly, monkey-patches ``MCP_TOOLS`` to add a
synthetic new-namespace entry, and asserts the guard
catches it. This is the same approach the v4.70.0
``test_v4700_guards.py`` uses for the other guards.
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

    We add ``scripts/`` to ``sys.path`` for the import
    and pop it again immediately so the test session's
    sys.path is not polluted. The guard module is also
    stashed on the test instance so subsequent calls
    don't re-import.
    """
    sys.path.insert(0, str(SCRIPTS))
    try:
        mod = importlib.import_module(name)
    finally:
        sys.path.pop(0)
    return mod


def test_namespace_doc_coverage_passes_in_soft_mode() -> None:
    """The v4.72.0 baseline covers all 23 namespaces, so the guard exits 0 in soft-warn mode."""
    guard = _import_guard("namespace_doc_coverage")
    rc = guard._run(REPO, enforce=False)
    assert rc == 0, f"soft-warn should return 0; got {rc}"


def test_namespace_doc_coverage_passes_in_enforce_mode() -> None:
    """With --enforce, the v4.72.0 baseline still passes (all 23 namespaces covered)."""
    guard = _import_guard("namespace_doc_coverage")
    rc = guard._run(REPO, enforce=True)
    assert rc == 0, f"enforce mode should return 0 on v4.72.0 baseline; got {rc}"


def test_namespace_doc_coverage_catches_new_namespace_without_example() -> None:
    """A new namespace added without a README example must fail --enforce.

    We monkey-patch ``MCP_TOOLS`` to add a synthetic
    entry in a brand-new namespace (``v4720audit``) that
    has no example in either README. The guard should
    catch the new namespace and return 1 in enforce
    mode.

    The synthetic entry is added to the in-memory
    ``arena.mcp.tool_registry.MCP_TOOLS`` attribute;
    the source file is not modified, so other tests in
    the session are unaffected.
    """
    guard = _import_guard("namespace_doc_coverage")
    sys.path.insert(0, str(REPO))
    try:
        from arena.mcp.tool_registry import MCP_TOOLS as real_tools
    finally:
        sys.path.pop(0)
    fake = list(real_tools) + [
        {
            "name": "v4720audit.uncovered_tool",
            "description": "Synthetic test entry for namespace-doc-coverage audit.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        }
    ]
    import arena.mcp.tool_registry as reg
    original = reg.MCP_TOOLS
    reg.MCP_TOOLS = fake
    try:
        # Soft-warn mode: still exits 0 (with a report).
        rc_soft = guard._run(REPO, enforce=False)
        assert rc_soft == 0, f"soft-warn should return 0; got {rc_soft}"
        # Enforce mode: must exit 1 because the new namespace has no README example.
        rc_enforce = guard._run(REPO, enforce=True)
        assert rc_enforce == 1, f"enforce should return 1 on new namespace; got {rc_enforce}"
    finally:
        reg.MCP_TOOLS = original
