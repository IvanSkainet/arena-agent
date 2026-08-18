#!/usr/bin/env python3
"""Reject test modules that turn product import failures into module skips."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

_PRODUCT_ROOTS = frozenset({"arena", "unified_bridge"})


def root_path() -> Path:
    return Path(__file__).resolve().parent.parent


def tests_path() -> Path:
    return root_path() / "tests"


def _is_product(module: str) -> bool:
    return any(
        module == root or module.startswith(root + ".")
        for root in _PRODUCT_ROOTS
    )


@dataclass
class ImportBindings(ast.NodeVisitor):
    pytest_modules: set[str] = field(default_factory=set)
    skip_functions: set[str] = field(default_factory=set)
    importlib_modules: set[str] = field(default_factory=set)
    import_functions: set[str] = field(default_factory=lambda: {"__import__"})

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            bound = alias.asname or alias.name
            if alias.name == "pytest":
                self.pytest_modules.add(bound)
            elif alias.name == "importlib":
                self.importlib_modules.add(bound)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "pytest":
            for alias in node.names:
                if alias.name == "skip":
                    self.skip_functions.add(alias.asname or alias.name)
        elif node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    self.import_functions.add(alias.asname or alias.name)


def _dynamic_import_name(
    call: ast.Call, bindings: ImportBindings
) -> str | None:
    function = call.func
    recognized = (
        isinstance(function, ast.Name)
        and function.id in bindings.import_functions
    ) or (
        isinstance(function, ast.Attribute)
        and function.attr == "import_module"
        and isinstance(function.value, ast.Name)
        and function.value.id in bindings.importlib_modules
    )
    if not recognized:
        return None
    candidate = call.args[0] if call.args else None
    if candidate is None:
        candidate = next(
            (keyword.value for keyword in call.keywords if keyword.arg == "name"),
            None,
        )
    if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
        return candidate.value
    return None


def _product_import_in(node: ast.AST, bindings: ImportBindings) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.ImportFrom):
            if child.module is not None and _is_product(child.module):
                return True
        elif isinstance(child, ast.Import):
            if any(_is_product(alias.name) for alias in child.names):
                return True
        elif isinstance(child, ast.Call):
            module = _dynamic_import_name(child, bindings)
            if module is not None and _is_product(module):
                return True
    return False


def _is_skip_call(call: ast.Call, bindings: ImportBindings) -> bool:
    function = call.func
    return (
        isinstance(function, ast.Name)
        and function.id in bindings.skip_functions
    ) or (
        isinstance(function, ast.Attribute)
        and function.attr == "skip"
        and isinstance(function.value, ast.Name)
        and function.value.id in bindings.pytest_modules
    )


def _module_skip_in(node: ast.AST, bindings: ImportBindings) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or not _is_skip_call(child, bindings):
            continue
        if any(
            keyword.arg == "allow_module_level"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in child.keywords
        ):
            return True
    return False


def scan_file(path: Path) -> list[int]:
    """Return try-statement lines that hide required product import failures."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bindings = ImportBindings()
    bindings.visit(tree)
    findings = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        and _product_import_in(node, bindings)
        and any(_module_skip_in(handler, bindings) for handler in node.handlers)
    ]
    return sorted(findings)


def collect() -> list[str]:
    findings = []
    root = root_path()
    candidates = set(tests_path().rglob("test_*.py"))
    candidates.update(tests_path().rglob("conftest.py"))
    for path in sorted(candidates):
        for line in scan_file(path):
            findings.append(f"{path.relative_to(root).as_posix()}:{line}")
    return findings


def main() -> int:
    findings = collect()
    if findings:
        print("required product imports fail open as module skips:")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print("OK: required product import failures remain collection errors")
    return 0


if __name__ == "__main__":  # pragma: no mutate - import/CLI boundary
    raise SystemExit(main())
