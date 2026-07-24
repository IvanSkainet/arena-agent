"""Tests for the v4.75.0 removal of the four bare tool names.

v4.69.0 deprecated ``ping`` / ``echo`` / ``exec`` /
``snapshot`` in favour of their namespaced ``exec.*``
twins. v4.75.0 ships the removal.

This test module pins the post-removal state.
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


_REMOVED_BARE_NAMES = ["ping", "echo", "exec", "snapshot"]
_NAMESPACED_TWINS = ["exec.ping", "exec.echo", "exec.exec", "exec.snapshot"]


@pytest.mark.parametrize("bare", _REMOVED_BARE_NAMES)
def test_bare_name_removed_from_catalogue(bare: str) -> None:
    names = {entry.get("name") for entry in MCP_TOOLS}
    assert bare not in names


@pytest.mark.parametrize("namespaced", _NAMESPACED_TWINS)
def test_namespaced_twin_present_in_catalogue(namespaced: str) -> None:
    names = {entry.get("name") for entry in MCP_TOOLS}
    assert namespaced in names


@pytest.mark.parametrize("namespaced", _NAMESPACED_TWINS)
def test_namespaced_twin_has_no_deprecation_message(namespaced: str) -> None:
    for entry in MCP_TOOLS:
        if entry.get("name") == namespaced:
            assert "deprecationMessage" not in entry
            assert "DEPRECATED" not in (entry.get("description") or "")
            break
    else:  # pragma: no cover
        pytest.fail(f"namespaced twin {namespaced!r} not found")


def test_legacy_name_guard_bare_names_is_mem_only() -> None:
    guard = _import_guard("legacy_name_guard")
    bare_names = guard._BARE_NAMES
    assert "ping" not in bare_names
    assert "echo" not in bare_names
    assert "exec" not in bare_names
    assert "snapshot" not in bare_names
    assert "mem.set" in bare_names
    assert "mem.get" in bare_names


def test_legacy_name_guard_whitelist_excludes_tool_exec_and_tool_misc() -> None:
    guard = _import_guard("legacy_name_guard")
    whitelist = guard._WHITELISTED_DISPATCH_FUNCS
    whitelisted_paths = {rel for rel, _fn in whitelist}
    assert "arena/mcp/tool_exec.py" not in whitelisted_paths
    assert "arena/mcp/tool_misc.py" not in whitelisted_paths
    assert "arena/mcp/tool_memory.py" in whitelisted_paths


@pytest.mark.parametrize("bare", _REMOVED_BARE_NAMES)
def test_dispatch_returns_none_for_removed_bare_name(bare: str) -> None:
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
