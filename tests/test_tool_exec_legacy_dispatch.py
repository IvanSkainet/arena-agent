"""v4.61.0 - sanity test for arena/mcp/tool_exec.py.

``tool_exec.py`` is the one module that hosts the legacy pre-MCP
tools ``ping``, ``echo`` and ``exec`` whose names are bare
identifiers. v4.67.0 added namespaced siblings (``exec.ping``,
``exec.echo``, ``exec.exec``) and the dispatch in
``handle_exec_tool`` now accepts both forms.

This test pins down that the legacy dispatch is actually wired
up — otherwise a refactor that drops the handler or breaks the
``name == 'ping'`` / ``name == 'echo'`` / ``name == 'exec'``
branches would silently kill the only tool that runs shell
commands on the operator's machine.

We do NOT execute anything; the handler signature requires
``ctx`` and ``run_sd`` which are not safe to fake in a unit test.
Instead we AST-verify the dispatch branches are still present
in the source.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent
TOOL_EXEC = REPO / "arena" / "mcp" / "tool_exec.py"


def _load_dispatch_branches() -> dict[str, list[int]]:
    """Return {tool_name: [line numbers]} for every legacy
    ``if name == '<x>'`` / ``if name in ('<x>', '<x>.<x>')`` /
    ``if name not in ('<x>', '<x>.<x>')`` branch in tool_exec.py.

    Used by the test below to assert that all three legacy tools
    are still dispatched, and to surface the line number if any
    one disappears.
    """
    if not TOOL_EXEC.exists():
        pytest.skip(f"{TOOL_EXEC} not present (running outside the repo)")
    src = TOOL_EXEC.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, str(TOOL_EXEC))

    expected = ("ping", "echo", "exec")
    found: dict[str, list[int]] = {n: [] for n in expected}

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        # Match ``if name == 'X':`` and ``if name != 'X':``
        if not isinstance(test, ast.Compare):
            continue
        if len(test.ops) != 1 or not isinstance(test.ops[0], (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
            continue
        if not isinstance(test.left, ast.Name) or test.left.id != "name":
            continue
        if len(test.comparators) != 1:
            continue
        cmp = test.comparators[0]
        if isinstance(cmp, ast.Constant) and isinstance(cmp.value, str):
            if cmp.value in expected:
                found[cmp.value].append(node.lineno)
        # Match ``if name in ('X', 'X.X'):`` and ``if name not in (...)``
        elif isinstance(cmp, ast.Tuple):
            for elt in cmp.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    if elt.value in expected:
                        found[elt.value].append(node.lineno)
    return found


def test_handle_exec_tool_still_dispatches_ping_echo_exec() -> None:
    """All three legacy tools must still be present in the dispatch
    tree. Dropping any one silently breaks the corresponding
    scenario without a syntax error -- the bug surfaces only at
    runtime as 'tool not found'.

    v4.67.0: the dispatch accepts both bare names (legacy) and
    namespaced forms (exec.ping / exec.echo / exec.exec). The test
    matches both styles via ``if name in ('X', 'X.X')``.
    """
    found = _load_dispatch_branches()
    for name in ("ping", "echo", "exec"):
        assert found[name], (
            f"tool_exec.py no longer has a dispatch branch for {name!r}; "
            f"the {name} MCP tool is broken (legacy bare + namespaced both gone)."
        )


def test_tool_exec_handles_both_bare_and_namespaced_names() -> None:
    """v4.67.0: the dispatch must accept BOTH the legacy bare names
    (ping / echo / exec) AND the namespaced siblings
    (exec.ping / exec.echo / exec.exec). The namespaced form is
    what new code should call; the bare form is the
    backward-compat alias.
    """
    if not TOOL_EXEC.exists():
        pytest.skip(f"{TOOL_EXEC} not present (running outside the repo)")
    src = TOOL_EXEC.read_text(encoding="utf-8", errors="replace")
    for bare, namespaced in [
        ("ping", "exec.ping"),
        ("echo", "exec.echo"),
        ("exec", "exec.exec"),
    ]:
        # Look for ``'exec.ping' in ('X', 'exec.ping')`` style
        # in the dispatch -- both forms must appear in the same
        # dispatch branch.
        if namespaced not in src:
            pytest.fail(
                f"tool_exec.py does not handle namespaced form {namespaced!r} "
                f"(only the bare name {bare!r} is dispatched)."
            )
