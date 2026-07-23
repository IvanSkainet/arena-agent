"""v4.61.0 - sanity test for arena/mcp/tool_exec.py.

``tool_exec.py`` is the one module exempted from the
"every handler must have namespace.action tool-name literals"
contract test, because it dispatches the legacy pre-MCP tools
``ping``, ``echo`` and ``exec`` whose names are bare identifiers.

This test pins down that the legacy dispatch is actually wired up
-- otherwise a refactor that drops the handler or breaks the
``name == 'ping'`` / ``name == 'echo'`` / ``name == 'exec'``
branches would silently kill the only tool that runs shell
commands on the operator's machine.

We do NOT execute anything; the handler signature requires
``ctx`` and ``run_sd`` which are not safe to fake in a unit test.
Instead we AST-verify the three dispatch branches are still
present in the source.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
TOOL_EXEC = REPO / "arena" / "mcp" / "tool_exec.py"


def _load_dispatch_branches() -> dict[str, list[int]]:
    """Return {tool_name: [line numbers]} for every legacy
    ``if name == '<x>'`` branch in tool_exec.py.

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
        # Match ``if name == 'X':`` and ``if name != 'X':``
        test = node.test
        if not isinstance(test, ast.Compare):
            continue
        if len(test.ops) != 1 or not isinstance(test.ops[0],
                                                 (ast.Eq, ast.NotEq)):
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


def test_handle_exec_tool_still_dispatches_ping_echo_exec() -> None:
    """All three legacy tools must still be present in the dispatch
    tree. Dropping any one silently breaks the corresponding
    scenario without a syntax error -- the bug surfaces only at
    runtime as "tool not found"."""
    found = _load_dispatch_branches()
    for name in ("ping", "echo", "exec"):
        assert found[name], (
            f"tool_exec.py no longer has an `if name == '{name}'` branch; "
            f"the {name} MCP tool is broken."
        )


def test_tool_exec_does_not_accidentally_introduce_dot_names() -> None:
    """v4.61.0 contract: tool_exec.py is the EXEMPT module for
    dot-style names. If a future change adds a ``'exec.ping'`` or
    similar to its dispatch, the test for the regular contract
    would silently start counting these names -- so we explicitly
    fail here and force the developer to update the contract
    snapshot deliberately instead."""
    src = TOOL_EXEC.read_text(encoding="utf-8", errors="replace")
    # Scan for any string literal matching the dot-style contract.
    pattern = re.compile(r"""['\"]([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)['\"]""")
    matches = sorted(set(pattern.findall(src)))
    assert not matches, (
        f"tool_exec.py now contains dot-style tool names {matches!r}. "
        "Either revert (legacy tools must stay bare) or remove the "
        "_LEGACY_HANDLER_MODULES whitelist in test_mcp_tool_contracts.py "
        "and regenerate tests/_mcp_contract_snapshot.json."
    )
