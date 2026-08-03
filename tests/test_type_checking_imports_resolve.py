"""Imports inside `if TYPE_CHECKING:` must point at modules that exist.

`arena/browser/cdp_client/network_har.py` imported `NetworkRequest` from
`arena.browser.cdp_client.network_types` -- a module that has never existed;
the class lives in `network_request`. Because the import sits under
`TYPE_CHECKING`, Python never executes it, so nothing failed at runtime and
nothing failed at import time. The annotation it supports was simply
unresolvable, which is the quiet way an "annotated" codebase stops being one.

Found by pyright's `reportMissingImports` while evaluating MegaLinter. Our
own checkers could not see it: ruff does not resolve imports, and pyrefly is
configured with `ignore_missing_imports = true` because the tree guards a
dozen optional dependencies that way.

The check is deliberately module-level only (`from X import Y` verifies that
`X` is importable, not that `Y` exists in it): resolving symbols would mean
importing optional dependencies we intentionally do not install.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCANNED = ("arena", "scripts", "bin")


def _type_checking_imports(tree: ast.Module) -> list[tuple[str, int]]:
    """Every module imported inside an `if TYPE_CHECKING:` block."""
    found: list[tuple[str, int]] = []

    def _is_type_checking(test: ast.expr) -> bool:
        if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
            return True
        return (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")

    for node in ast.walk(tree):
        if not (isinstance(node, ast.If) and _is_type_checking(node.test)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom):
                # Relative imports resolve against the package; skip them
                # rather than reimplement importlib's resolution rules.
                if sub.level or not sub.module:
                    continue
                found.append((sub.module, sub.lineno))
            elif isinstance(sub, ast.Import):
                for alias in sub.names:
                    found.append((alias.name, sub.lineno))
    return found


def _first_party(module: str) -> bool:
    """Only check our own modules; third-party stubs may be absent by design."""
    return module.split(".")[0] == "arena"


def test_type_checking_imports_point_at_real_modules():
    offenders: list[str] = []
    for root in SCANNED:
        for path in sorted((REPO / root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for module, lineno in _type_checking_imports(tree):
                if not _first_party(module):
                    continue
                try:
                    spec = importlib.util.find_spec(module)
                except (ImportError, ValueError, ModuleNotFoundError):
                    spec = None
                if spec is None:
                    rel = path.relative_to(REPO).as_posix()
                    offenders.append(
                        f"{rel}:{lineno} imports {module!r} under TYPE_CHECKING, "
                        "but no such module exists")
    assert offenders == [], "\n".join(offenders)


def test_network_har_annotation_resolves():
    """Pin the specific regression."""
    import ast as _ast

    from arena.browser.cdp_client.network_request import NetworkRequest

    src = (REPO / "arena" / "browser" / "cdp_client" / "network_har.py").read_text(
        encoding="utf-8")
    modules = {m for m, _ in _type_checking_imports(_ast.parse(src))}
    assert "arena.browser.cdp_client.network_types" not in modules, (
        "network_har still imports NetworkRequest from the nonexistent "
        "network_types module")
    assert "arena.browser.cdp_client.network_request" in modules
    assert NetworkRequest.__module__.endswith("network_request")
