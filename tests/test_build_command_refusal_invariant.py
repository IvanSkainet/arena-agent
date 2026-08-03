"""`build_command` must never hand `None` to subprocess.

The contract is written in its docstring: *argv is None when execution is
refused (fail-closed)*. Two things have to hold for that to be true, and only
one of them did.

**The invariant.** Every `return None, info` must carry `refused: True`, because
the single call site checks exactly that before using argv. Walked with the AST
rather than trusted.

**The hole this found.** `runtime_cmd` came from
``_managed_runtime_path(lang) or (_resolve_win32_runtime(lang) if ... else
default_runtime)``, and `_resolve_win32_runtime` returns None when the host has
only the WindowsApps alias shim instead of a real interpreter. That None went
straight into `argv[0]`, so instead of a refusal the sandbox path raised

    TypeError: expected str, bytes or os.PathLike object, not NoneType

from inside `subprocess.run` -- opaque, and fail-open in the sense that matters:
the caller learns nothing about *why* the run could not happen. Reproduced by
calling `_runtime_invocation(..., command=None)` and handing the result to
subprocess before the fix.

Green here does not prove the sandbox confines anything; that is
`tests/test_autonomy_*`. It proves the refusal path cannot degrade into a crash.
"""
from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from arena.autonomy import runner  # noqa: E402

RUNNER_SRC = REPO / "arena" / "autonomy" / "runner.py"


def _build_command_node() -> ast.FunctionDef:
    tree = ast.parse(RUNNER_SRC.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "build_command")


def test_every_none_argv_is_paired_with_refused_true():
    """The invariant the single call site relies on."""
    offenders = []
    for node in ast.walk(_build_command_node()):
        if not (isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple)):
            continue
        first, second = node.value.elts[0], node.value.elts[1]
        if not (isinstance(first, ast.Constant) and first.value is None):
            continue
        info = ast.unparse(second)
        if "'refused': True" not in info and '"refused": True' not in info:
            offenders.append(f"line {node.lineno}: {info[:70]}")
    assert offenders == [], (
        "these return a None argv without refused=True, so the caller will "
        f"pass None to subprocess: {offenders}"
    )


def test_the_call_site_still_guards_on_refused():
    """If the guard moves, the invariant above stops protecting anything."""
    src = RUNNER_SRC.read_text(encoding="utf-8")
    assert 'if info.get("refused"):' in src
    assert "assert argv_cmd is not None" in src, (
        "the narrowing assert is gone; a future None would reach subprocess"
    )


def test_missing_windows_runtime_refuses_instead_of_crashing(monkeypatch):
    """The bug: no real interpreter must be a refusal, not a TypeError."""
    scratch = Path(tempfile.mkdtemp())
    code = scratch / "x.py"
    code.write_text("print(1)", encoding="utf-8")

    monkeypatch.setattr(runner, "_resolve_win32_runtime", lambda lang: None)
    monkeypatch.setattr(runner, "_managed_runtime_path", lambda lang: None)

    argv, info = runner.build_command("win32", {"resources": {}}, "python3",
                                      code, scratch)
    assert argv is None
    assert info.get("refused") is True
    assert "not found" in str(info.get("note", "")).lower()


def test_a_resolvable_runtime_still_builds_argv():
    """The refusal must not swallow the normal path."""
    scratch = Path(tempfile.mkdtemp())
    code = scratch / "x.py"
    code.write_text("print(1)", encoding="utf-8")

    argv, info = runner.build_command("linux", {"resources": {}}, "python",
                                      code, scratch)
    if info.get("refused"):
        pytest.skip(f"sandbox unsupported on this host: {info.get('note')}")
    assert argv is not None
    assert argv[0], "argv[0] is empty"


def test_none_in_argv_would_break_subprocess():
    """Documents why the refusal matters, by showing the failure it prevents."""
    argv = runner._runtime_invocation("python", None, Path("/tmp/x.py"))  # type: ignore[arg-type]
    assert argv[0] is None
    with pytest.raises(TypeError):
        subprocess.run(argv, capture_output=True, timeout=5)
