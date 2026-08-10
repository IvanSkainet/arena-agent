"""No test module may carry its own `node -e` timeout.

Five modules once did, at two different values, both sized on a warm Linux
runner. windows-latest went red twice on the 10 s pair before the pattern was
recognised. The literals are the bug; this gate makes reintroducing one fail
immediately rather than months later on someone else's PR.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests._node_budget import NODE_TIMEOUT_S, node_timeout  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

# Modules that shell out to Node and must therefore use the shared budget.
NODE_MODULES = (
    "test_terminal_osc.py",
    "test_terminal_ansi.py",
    "test_overview_gpu_errors_js.py",
    "test_overview_toolbar_js.py",
    "test_proposals_tab_js.py",
    "test_error_meta_escaping_v4_169_33.py",
)


def test_every_node_module_uses_the_shared_budget():
    for name in NODE_MODULES:
        src = (TESTS / name).read_text(encoding="utf-8")
        assert "node_timeout()" in src, f"{name} does not use the shared node budget"


def test_no_node_module_hardcodes_a_subprocess_timeout():
    offenders = []
    for name in NODE_MODULES:
        path = TESTS / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "run":
                continue
            for kw in node.keywords:
                if kw.arg == "timeout" and isinstance(kw.value, ast.Constant):
                    offenders.append(f"{name}:{kw.value.lineno} timeout={kw.value.value}")
    assert offenders == [], offenders


def test_the_module_list_has_not_gone_stale():
    """A new Node-shelling module must be added to NODE_MODULES.

    Otherwise this gate quietly stops covering the thing it exists for.
    """
    missing = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name in NODE_MODULES or path.name == "test_node_budget.py":
            continue
        src = path.read_text(encoding="utf-8")
        if re.search(r"""\[\s*["']node["']\s*,\s*["']-e["']""", src):
            missing.append(path.name)
    assert missing == [], f"these modules run `node -e` but are not in NODE_MODULES: {missing}"


def test_windows_gets_a_larger_allowance_than_the_old_literals():
    """The point of the change: the budget must exceed what used to fail."""
    assert NODE_TIMEOUT_S >= 30
    assert node_timeout() >= NODE_TIMEOUT_S


def test_env_override_can_only_raise_the_budget(monkeypatch):
    monkeypatch.setenv("ARENA_TEST_NODE_TIMEOUT", "1")
    assert node_timeout() == NODE_TIMEOUT_S
    monkeypatch.setenv("ARENA_TEST_NODE_TIMEOUT", str(NODE_TIMEOUT_S + 45))
    assert node_timeout() == NODE_TIMEOUT_S + 45
    monkeypatch.setenv("ARENA_TEST_NODE_TIMEOUT", "not-a-number")
    assert node_timeout() == NODE_TIMEOUT_S
