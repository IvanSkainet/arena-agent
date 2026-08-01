"""Tests for the v4.75.0 / v4.78.0 removal of bare tool names.

v4.69.0 deprecated four bare tool names
(``ping`` / ``echo`` / ``exec`` / ``snapshot``) in
favour of their namespaced ``exec.*`` twins. v4.75.0
shipped the removal of those four.

v4.71.0 deprecated two more bare names (``mem.set`` /
``mem.get``) in favour of the namespaced
``memory.*`` twins. v4.78.0 ships the removal of
those two.

This test module pins the post-removal state for both
batches.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"


def _import_guard(name: str):
    sys.path.insert(0, str(SCRIPTS))
    try:
        mod = importlib.import_module(name)
    finally:
        sys.path.pop(0)
    return mod


try:
    from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
except Exception:  # pragma: no cover
    pytest.skip("MCP_TOOLS not importable", allow_module_level=True)


_V4750_REMOVED = ["ping", "echo", "exec", "snapshot"]
_V4750_NAMESPACED = ["exec.ping", "exec.echo", "exec.exec", "exec.snapshot"]
_V4780_REMOVED = ["mem.set", "mem.get"]
_V4780_NAMESPACED = ["memory.import", "memory.recall", "memory.digest", "memory.export"]


@pytest.mark.parametrize("bare", _V4750_REMOVED)
def test_v4750_bare_name_removed_from_catalogue(bare: str) -> None:
    names = {entry.get("name") for entry in MCP_TOOLS}
    assert bare not in names


@pytest.mark.parametrize("namespaced", _V4750_NAMESPACED)
def test_v4750_namespaced_twin_present_in_catalogue(namespaced: str) -> None:
    names = {entry.get("name") for entry in MCP_TOOLS}
    assert namespaced in names


@pytest.mark.parametrize("namespaced", _V4750_NAMESPACED)
def test_v4750_namespaced_twin_has_no_deprecation_message(namespaced: str) -> None:
    for entry in MCP_TOOLS:
        if entry.get("name") == namespaced:
            assert "deprecationMessage" not in entry
            assert "DEPRECATED" not in (entry.get("description") or "")
            break
    else:  # pragma: no cover
        pytest.fail(f"namespaced twin {namespaced!r} not found")


def test_legacy_name_guard_bare_names_is_empty_v4780() -> None:
    """v4.78.0: the bare-name set is now empty."""
    guard = _import_guard("legacy_name_guard")
    bare_names = guard._BARE_NAMES
    for n in ["ping", "echo", "exec", "snapshot", "mem.set", "mem.get"]:
        assert n not in bare_names
    assert len(bare_names) == 0


def test_legacy_name_guard_whitelist_is_empty_v4780() -> None:
    """v4.78.0: the whitelist is also empty."""
    guard = _import_guard("legacy_name_guard")
    whitelist = guard._WHITELISTED_DISPATCH_FUNCS
    assert len(whitelist) == 0


@pytest.mark.parametrize("bare", _V4750_REMOVED)
def test_v4750_dispatch_returns_none_for_removed_bare_name(bare: str) -> None:
    from arena.mcp.tool_exec import handle_exec_tool
    from arena.mcp.tool_misc import handle_misc_tool

    class _StubCtx:
        pass

    def _run_stub(*args, **kwargs):
        return 0, "", ""

    if bare in ("ping", "echo", "exec"):
        result = handle_exec_tool(bare, {"cmd": "true"} if bare == "exec" else {"text": "x"} if bare == "echo" else {}, ctx=_StubCtx(), run_sd=_run_stub)
        assert result is None
    elif bare == "snapshot":
        result = handle_misc_tool(bare, {}, ctx=_StubCtx(), run_local=_run_stub)
        assert result is None


@pytest.mark.parametrize("bare", _V4780_REMOVED)
def test_v4780_bare_name_removed_from_catalogue(bare: str) -> None:
    names = {entry.get("name") for entry in MCP_TOOLS}
    assert bare not in names


@pytest.mark.parametrize("namespaced", _V4780_NAMESPACED)
def test_v4780_namespaced_twin_present_in_catalogue(namespaced: str) -> None:
    names = {entry.get("name") for entry in MCP_TOOLS}
    assert namespaced in names


@pytest.mark.parametrize("bare", _V4780_REMOVED)
def test_v4780_dispatch_returns_none_for_removed_bare_name(bare: str) -> None:
    from arena.mcp.tool_memory import handle_memory_tool

    class _StubCtx:
        pass

    def _run_stub(*args, **kwargs):
        return 0, "", ""

    if bare == "mem.set":
        result = handle_memory_tool(bare, {"key": "k", "value": "v"}, ctx=_StubCtx(), run_local=_run_stub)
    else:
        result = handle_memory_tool(bare, {"query": "x"}, ctx=_StubCtx(), run_local=_run_stub)
    assert result is None
