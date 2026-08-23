"""No test module may carry its own `git` subprocess timeout.

Five modules once did, at four different values -- 5, 10, 15 and 60 seconds --
for the same handful of operations. `git commit` was allowed 5 s in one module
and 10 s in another, decided by whichever file had been copied from.

The 5 s literals went red on windows-latest in PR #144 while every Linux and
macOS job passed, and a rerun of the same commit was green (#145). The literals
are the bug; this gate makes reintroducing one fail immediately rather than
months later on someone else's unrelated PR.

Deliberately mirrors `tests/test_node_budget.py`, including the staleness
check, so the two budgets are one pattern rather than two.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests._git_budget import GIT_TIMEOUT_S, git_timeout  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"

# Modules that shell out to git and must therefore use the shared budget.
GIT_MODULES = (
    "test_git_tools.py",
    "test_admin_proposal_core.py",
    "test_gitleaks_allowlist_v4_169_42.py",
    "test_failopen_ratchet.py",
    "test_mutation_sweep_fails_closed.py",
)

# Modules that invoke git without any timeout at all. Listed rather than
# silently ignored: a git call with no timeout cannot flake on a slow runner,
# it hangs the job outright, which is a different defect than #145 and is not
# in scope here.
_NO_TIMEOUT_CALLERS = frozenset({"test_install_termux.py", "test_pre_release_check.py"})


def _git_calls(path: Path) -> list[ast.Call]:
    """Every subprocess call in `path` whose argv literal starts with "git"."""
    calls = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in {"run", "check_output", "call", "Popen"}:
            continue
        if not node.args:
            continue
        argv = node.args[0]
        if not (isinstance(argv, ast.List) and argv.elts):
            continue
        head = argv.elts[0]
        if isinstance(head, ast.Constant) and head.value == "git":
            calls.append(node)
    return calls


def test_every_git_module_uses_the_shared_budget() -> None:
    for name in GIT_MODULES:
        src = (TESTS / name).read_text(encoding="utf-8")
        assert "git_timeout()" in src, f"{name} does not use the shared git budget"


def test_no_test_module_hardcodes_a_git_subprocess_timeout() -> None:
    """The regression this file exists for: a bare number at a git call site."""
    offenders = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == "test_git_budget.py":
            continue
        for call in _git_calls(path):
            for kw in call.keywords:
                if kw.arg == "timeout" and isinstance(kw.value, ast.Constant):
                    offenders.append(f"{path.name}:{kw.value.lineno} timeout={kw.value.value}")
    assert offenders == [], (
        f"these git calls hardcode a timeout instead of using git_timeout(): {offenders}"
    )


def test_the_module_list_has_not_gone_stale() -> None:
    """A new git-shelling module must join GIT_MODULES.

    Otherwise the gate quietly stops covering the thing it exists for -- it
    would still pass while a fresh module reintroduced the original bug.
    """
    missing = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name in GIT_MODULES or path.name == "test_git_budget.py":
            continue
        if path.name in _NO_TIMEOUT_CALLERS:
            continue
        if _git_calls(path):
            missing.append(path.name)
    assert missing == [], f"these modules shell out to git but are not in GIT_MODULES: {missing}"


def test_windows_gets_a_larger_allowance_than_the_literal_that_failed() -> None:
    """The point of the change: the budget must exceed what actually broke.

    5 s is the literal that timed out on windows-latest. Measured cost of the
    slowest real operation there was ~62 ms, so the failure was runner
    contention rather than git being slow -- which is exactly why the budget
    needs headroom instead of a tighter number.
    """
    assert GIT_TIMEOUT_S >= 15
    assert git_timeout() >= GIT_TIMEOUT_S


def test_env_override_can_only_raise_the_budget(monkeypatch) -> None:
    monkeypatch.setenv("ARENA_TEST_GIT_TIMEOUT", "1")
    assert git_timeout() == GIT_TIMEOUT_S, "override must never lower the budget"
    monkeypatch.setenv("ARENA_TEST_GIT_TIMEOUT", str(GIT_TIMEOUT_S + 45))
    assert git_timeout() == GIT_TIMEOUT_S + 45
    monkeypatch.setenv("ARENA_TEST_GIT_TIMEOUT", "not-a-number")
    assert git_timeout() == GIT_TIMEOUT_S, "a malformed override must fall back, not crash"
