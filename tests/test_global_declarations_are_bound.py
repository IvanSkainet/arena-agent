"""Every `global X` must have a module-level `X` to bind.

`arena/desktop/cli/focus.py` declared `global _wm_started` and read it, but no
module-level assignment ever created the name. The first call raised
`NameError: name '_wm_started' is not defined`, which took down `click`,
`key` and `type_text` in `arena/desktop/cli/input.py` -- they call
`_ensure_wm()` before every input event. So the entire CLI desktop-input path
was dead, and nothing noticed: the module imports fine, and the failure only
appears when the function actually runs.

This is the same shape as the v4.155.0 star-import bugs (a name that reads as
bound but is not), so the guard is written for the class rather than the one
file. Found by pylint (`used-before-assignment`) and pyright
(`reportUnboundVariable`) independently while evaluating MegaLinter.

Note the deliberate scope: only names that are *read* matter. A `global X`
followed solely by `X = ...` is legal and common (that is how a module
initialises lazy state), so those are not reported.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCANNED = ("arena", "scripts", "bin")


def _module_level_bindings(tree: ast.Module) -> set[str]:
    """Names that exist at module scope after import."""
    bound: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        bound.add(sub.id)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            if isinstance(node.target, ast.Name):
                bound.add(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                # A star import may provide anything; treat it as opaque and
                # skip the file rather than guess (see _uses_star_import).
                bound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            # Conditional/guarded module-level assignment still binds the name.
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign):
                    for target in sub.targets:
                        for leaf in ast.walk(target):
                            if isinstance(leaf, ast.Name):
                                bound.add(leaf.id)
                elif isinstance(sub, (ast.AnnAssign, ast.AugAssign)):
                    if isinstance(sub.target, ast.Name):
                        bound.add(sub.target.id)
                elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for alias in sub.names:
                        bound.add(alias.asname or alias.name.split(".")[0])
                elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    bound.add(sub.name)
    return bound


def _uses_star_import(tree: ast.Module) -> bool:
    return any(
        isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
        for n in ast.walk(tree))


def _offenders() -> list[str]:
    problems: list[str] = []
    for root in SCANNED:
        for path in sorted((REPO / root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            if _uses_star_import(tree):
                continue  # cannot know what the star provided
            bound = _module_level_bindings(tree)
            for func in ast.walk(tree):
                if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                declared: set[str] = set()
                for node in ast.walk(func):
                    if isinstance(node, ast.Global):
                        declared.update(node.names)
                if not declared:
                    continue
                read: set[str] = set()
                assigned: set[str] = set()
                for node in ast.walk(func):
                    if isinstance(node, ast.Name) and node.id in declared:
                        if isinstance(node.ctx, ast.Load):
                            read.add(node.id)
                        else:
                            assigned.add(node.id)
                # Only a READ of an unbound global is a NameError waiting to
                # happen; write-only globals create the name themselves.
                for name in sorted(read - bound):
                    rel = path.relative_to(REPO).as_posix()
                    problems.append(
                        f"{rel}:{func.lineno} {func.name}() reads global "
                        f"{name!r}, which has no module-level binding")
    return problems


def test_no_function_reads_an_unbound_global():
    offenders = _offenders()
    assert offenders == [], "\n".join(offenders)


def test_the_focus_module_binds_its_flag():
    """Pin the specific regression: import must create the name."""
    from arena.desktop.cli import focus

    assert hasattr(focus, "_wm_started"), (
        "_ensure_wm() declares `global _wm_started` and reads it; without a "
        "module-level binding the first call raises NameError and every CLI "
        "desktop input (click/key/type_text) dies")
    assert focus._wm_started is False


def test_ensure_wm_is_callable_without_a_display(monkeypatch):
    """The real failure path, executed: no DISPLAY must return False, not raise."""
    from arena.desktop.cli import focus

    monkeypatch.setattr(focus, "_wm_started", False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(focus, "_detect_wm", lambda: None)
    try:
        result = focus._ensure_wm()
    except NameError as exc:  # pragma: no cover - the bug being guarded
        pytest.fail(f"_ensure_wm() raised NameError: {exc}")
    assert result is False
