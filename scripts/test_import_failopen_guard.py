#!/usr/bin/env python3
"""Reject test modules that turn product import failures into module skips."""
from __future__ import annotations

import ast
from pathlib import Path

_PRODUCT_PREFIXES = ("arena", "unified_bridge")


def root_path() -> Path:
    return Path(__file__).resolve().parent.parent


def tests_path() -> Path:
    return root_path() / "tests"


def _product_import_in(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.ImportFrom):
            module = child.module
            if module is not None and module.startswith(_PRODUCT_PREFIXES):
                return True
        elif isinstance(child, ast.Import):
            if any(alias.name.startswith(_PRODUCT_PREFIXES) for alias in child.names):
                return True
        elif isinstance(child, ast.Call):
            function = child.func
            if (
                isinstance(function, ast.Attribute)
                and function.attr == "import_module"
                and child.args
                and isinstance(child.args[0], ast.Constant)
                and isinstance(child.args[0].value, str)
                and child.args[0].value.startswith(_PRODUCT_PREFIXES)
            ):
                return True
    return False


def _module_skip_in(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        function = child.func
        if not (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "pytest"
            and function.attr == "skip"
        ):
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
    findings: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try) or not _product_import_in(node):
            continue
        if any(_module_skip_in(handler) for handler in node.handlers):
            findings.append(node.lineno)
    return sorted(findings)


def collect() -> list[str]:
    findings = []
    root = root_path()
    for path in sorted(tests_path().rglob("test_*.py")):
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
