"""Tests for the v4.73.0 shadow-detection tightening.

v4.70.0-v4.71.0 used a loose shadow heuristic (matching
any shared verb between descriptions) that produced many
false positives (``fs.list`` ↔ ``secrets.list``, etc.)
and required the "skip deprecated entries" workaround
to avoid double-counting the ``mem.*`` deprecation.

v4.73.0 tightens the heuristic to two strict cases:

1. **Identical-description shadow.** Two entries from
   different namespaces have **exactly equal**
   ``description`` strings (after stripping the
   deprecation marker suffix).

2. **Alias shadow.** A description contains the
   exact phrase ``"alias for <other-name>"`` (case
   insensitive).

The v4.70.0 verb-overlap heuristic is removed entirely.
This test module pins the new behaviour so a future
maintainer who re-introduces the loose heuristic (and
the false positives) trips a red X.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

# Locate the repo root from this test file's location.
REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"


def _import_guard(name: str):
    """Import a guard module from scripts/."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        mod = importlib.import_module(name)
    finally:
        sys.path.pop(0)
    return mod


def test_handler_namespace_consistency_passes_on_baseline() -> None:
    """The v4.73.0 baseline (after v4.72.0 docs + v4.71.0 mem.* deprecation) has no shadows."""
    guard = _import_guard("handler_namespace_consistency")
    rc = guard._run(REPO)
    assert rc == 0, f"handler_namespace_consistency failed on v4.73.0 baseline: rc={rc}"


def test_catches_identical_description_shadow() -> None:
    """Two entries with identical descriptions in different namespaces must fail the guard.

    We inject a synthetic shadow pair: ``fs.test_shadow``
    and ``git.test_shadow`` with the same description.
    The guard should detect this as a shadow and return 1.
    """
    guard = _import_guard("handler_namespace_consistency")
    sys.path.insert(0, str(REPO))
    try:
        from arena.mcp.tool_registry import MCP_TOOLS as real_tools
    finally:
        sys.path.pop(0)
    fake = list(real_tools) + [
        {
            "name": "fs.test_shadow_identical",
            "description": "v4.73.0 test: identical-description shadow.",
            "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}, "additionalProperties": False},
        },
        {
            "name": "git.test_shadow_identical",
            "description": "v4.73.0 test: identical-description shadow.",
            "inputSchema": {"type": "object", "properties": {"y": {"type": "string"}}, "additionalProperties": False},
        },
    ]
    import arena.mcp.tool_registry as reg
    original = reg.MCP_TOOLS
    reg.MCP_TOOLS = fake
    try:
        rc = guard._run(REPO)
        assert rc == 1, f"expected rc=1 on identical-description shadow, got {rc}"
    finally:
        reg.MCP_TOOLS = original


def test_catches_alias_for_shadow() -> None:
    """A description containing "alias for X" pointing to a tool in another namespace must fail."""
    guard = _import_guard("handler_namespace_consistency")
    sys.path.insert(0, str(REPO))
    try:
        from arena.mcp.tool_registry import MCP_TOOLS as real_tools
    finally:
        sys.path.pop(0)
    fake = list(real_tools) + [
        {
            "name": "fs.test_alias_target",
            "description": "v4.73.0 test: target for alias shadow.",
            "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}, "additionalProperties": False},
        },
        {
            "name": "git.test_alias_source",
            "description": "alias for fs.test_alias_target",
            "inputSchema": {"type": "object", "properties": {"y": {"type": "string"}}, "additionalProperties": False},
        },
    ]
    import arena.mcp.tool_registry as reg
    original = reg.MCP_TOOLS
    reg.MCP_TOOLS = fake
    try:
        rc = guard._run(REPO)
        assert rc == 1, f"expected rc=1 on alias-for shadow, got {rc}"
    finally:
        reg.MCP_TOOLS = original


def test_does_not_flag_verb_overlap_as_shadow() -> None:
    """Two entries with shared verbs in description but different concepts must NOT be flagged.

    This is the regression test for the v4.70.0
    verb-overlap heuristic that the v4.73.0 tighten
    removes. ``fs.list`` and ``secrets.list`` both
    contain the verb "list" in their descriptions, but
    they are different concepts (filesystem listing vs.
    secret-keys listing); under the v4.70.0 heuristic
    they would have been flagged as a shadow, under
    v4.73.0 they are not.
    """
    guard = _import_guard("handler_namespace_consistency")
    sys.path.insert(0, str(REPO))
    try:
        from arena.mcp.tool_registry import MCP_TOOLS as real_tools
    finally:
        sys.path.pop(0)
    fake = list(real_tools) + [
        {
            "name": "fs.test_verb_overlap",
            "description": "List files in a directory tree, returning names and sizes.",
            "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "additionalProperties": False},
        },
        {
            "name": "secrets.test_verb_overlap",
            "description": "List available secret keys for diagnostics (values are never returned).",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    ]
    import arena.mcp.tool_registry as reg
    original = reg.MCP_TOOLS
    reg.MCP_TOOLS = fake
    try:
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            guard._run(REPO)
        report = buf.getvalue()
        assert "shadow namespace" not in report, (
            f"verb-overlap incorrectly flagged as shadow:\n{report}"
        )
    finally:
        reg.MCP_TOOLS = original
