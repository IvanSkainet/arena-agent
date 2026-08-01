"""v4.75.0 - sanity test for arena/mcp/tool_exec.py.

v4.67.0: ``tool_exec.py`` was the one module that hosted
the legacy pre-MCP tools ``ping``, ``echo`` and
``exec`` whose names were bare identifiers. v4.67.0
added namespaced siblings (``exec.ping``, ``exec.echo``,
``exec.exec``) and the dispatch in ``handle_exec_tool``
accepted both forms during the v4.69.0 deprecation
window.

v4.75.0: the v4.69.0 deprecation window has expired
and the bare names were removed from the catalogue
and the dispatchers. ``tool_exec.py`` now accepts
**only** the namespaced form (``exec.ping`` /
``exec.echo`` / ``exec.exec``). This test pins down
that the namespaced dispatch is wired up; a refactor
that drops the handler or breaks the
``name == 'exec.ping'`` / ``name == 'exec.echo'`` /
``name != 'exec.exec'`` branches would silently kill
the only tool that runs shell commands on the
operator's machine.

We do NOT execute anything; the handler signature
requires ``ctx`` and ``run_sd`` which are not safe to
fake in a unit test. Instead we AST-verify the
dispatch branches are still present in the source.
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
    """Return {tool_name: [line numbers]} for every
    namespaced ``if name == '<x>'`` / ``if name != '<x>'``
    branch in tool_exec.py.

    Used by the test below to assert that all three
    namespaced tools (exec.ping / exec.echo / exec.exec)
    are still dispatched, and to surface the line number
    if any one disappears.
    """
    if not TOOL_EXEC.exists():
        pytest.skip(f"{TOOL_EXEC} not present (running outside the repo)")
    src = TOOL_EXEC.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, str(TOOL_EXEC))

    expected = ("exec.ping", "exec.echo", "exec.exec")
    found: dict[str, list[int]] = {n: [] for n in expected}

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare):
            continue
        if len(test.ops) != 1 or not isinstance(test.ops[0], (ast.Eq, ast.NotEq)):
            continue
        if not isinstance(test.left, ast.Name) or test.left.id != "name":
            continue
        if len(test.comparators) != 1:
            continue
        cmp = test.comparators[0]
        if isinstance(cmp, ast.Constant) and isinstance(cmp.value, str):
            if cmp.value in expected:
                found[cmp.value].append(node.lineno)
    return found


def test_handle_exec_tool_still_dispatches_namespaced_tools() -> None:
    found = _load_dispatch_branches()
    for name in ("exec.ping", "exec.echo", "exec.exec"):
        assert found[name], (
            f"tool_exec.py no longer has a dispatch branch for {name!r}; "
            f"the {name} MCP tool is broken."
        )


def test_tool_exec_does_not_dispatch_bare_names() -> None:
    """v4.75.0: the dispatcher must NOT accept the bare forms
    (ping / echo / exec). The v4.69.0 deprecation window
    has expired; calls to the bare form return None and
    the bridge reports no-such-tool.

    This test guards against an accidental re-introduction
    of the bare-name branches. A future maintainer who
    adds them back (for example, by reverting v4.75.0)
    trips a red X.
    """
    if not TOOL_EXEC.exists():
        pytest.skip(f"{TOOL_EXEC} not present (running outside the repo)")
    src = TOOL_EXEC.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, str(TOOL_EXEC))

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare):
            continue
        if len(test.ops) != 1:
            continue
        if not isinstance(test.left, ast.Name) or test.left.id != "name":
            continue
        if len(test.comparators) != 1:
            continue
        cmp = test.comparators[0]
        if isinstance(cmp, ast.Constant) and isinstance(cmp.value, str):
            if cmp.value in ("ping", "echo", "exec"):
                pytest.fail(
                    f"tool_exec.py has a dispatch branch for the bare name "
                    f"{cmp.value!r}; v4.75.0 removed all bare-name branches. "
                    f"Use the namespaced form (exec.*) instead."
                )
        elif isinstance(cmp, ast.Tuple):
            for elt in cmp.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    if elt.value in ("ping", "echo", "exec"):
                        pytest.fail(
                            f"tool_exec.py has a dispatch branch that includes "
                            f"the bare name {elt.value!r}; v4.75.0 removed all "
                            f"bare-name branches."
                        )
