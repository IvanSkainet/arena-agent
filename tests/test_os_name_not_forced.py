"""No test may change ``os.name`` for the whole process."""
# ``os`` is one module object. A test that sets ``os.name`` changes it for every
# library running in that process until the test ends: pytest, coverage,
# ``sysconfig``, ``pathlib``. coverage re-reads the ``sysconfig`` install paths
# whenever ``sys.path`` has changed, at the moment it first sees a new file. When
# that moment fell inside a test with ``os.name`` forced to ``"nt"`` on macOS,
# ``sysconfig`` raised and the pytest worker died with an INTERNALERROR (#558).
#
# A module that needs the answer asks a function of its own, ``_on_windows()``,
# and a test replaces that function.
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

from arena.exec import interpreters
from arena.relay import terminal
from arena.resources import mission_identifier

TESTS = Path(__file__).resolve().parent

# "os.name", or a dotted path that ends in it, given as a string to setattr or patch.
DOTTED = re.compile(r"(?:^|\.)os\.name$")


def _is_os(node: ast.AST) -> bool:
    """Tell whether the expression is ``os`` or ``<something>.os``."""
    if isinstance(node, ast.Name):
        return node.id == "os"
    return isinstance(node, ast.Attribute) and node.attr == "os"


def _is_os_name(node: ast.AST) -> bool:
    """Tell whether the expression is ``os.name``."""
    if not isinstance(node, ast.Attribute):
        return False
    return node.attr == "name" and _is_os(node.value)


def _text(node: ast.AST) -> str:
    """Return the string a literal holds, or an empty string for anything else."""
    value = node.value if isinstance(node, ast.Constant) else None
    return value if isinstance(value, str) else ""


def _call_forces(call: ast.Call) -> bool:
    """Tell whether a call names ``os.name`` as the thing to replace."""
    args = call.args
    if any(_is_os(first) and _text(second) == "name" for first, second in zip(args, args[1:])):
        return True
    return any(DOTTED.search(_text(arg)) for arg in args)


def _assigned(node: ast.AST) -> list[ast.AST]:
    """Return what an assignment statement assigns to."""
    if isinstance(node, ast.Assign):
        return node.targets
    return [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign)) else []


def _forces(node: ast.AST) -> bool:
    """Tell whether one node of the tree sets ``os.name``."""
    if isinstance(node, ast.Call):
        return _call_forces(node)
    return any(_is_os_name(target) for target in _assigned(node))


def forcing_lines(text: str) -> list[int]:
    """Return the numbers of the lines where a statement that sets ``os.name`` begins."""
    return sorted({node.lineno for node in ast.walk(ast.parse(text)) if _forces(node)})


@pytest.mark.parametrize("statement", [
    'monkeypatch.setattr(os, "name", "nt")',
    "monkeypatch.setattr(os, 'name', 'posix')",
    'monkeypatch.setattr(interp.os, "name", os_name)',
    'monkeypatch.setattr("os.name", "nt")',
    'monkeypatch.setattr("arena.exec.interpreters.os.name", "nt")',
    'with mock.patch("os.name", "nt"):\n    pass',
    'with mock.patch.object(os, "name", "nt"):\n    pass',
    'setattr(os, "name", "nt")',
    'os.name = "nt"',
    'module.os.name = "nt"',
    'monkeypatch.setattr(\n    os,\n    "name",\n    "nt",\n)',
    'monkeypatch.setattr(\n    "os.name",\n    "nt",\n)',
])
def test_every_way_of_forcing_is_recognised(statement):
    assert forcing_lines(statement) == [1]


@pytest.mark.parametrize("statement", [
    'if os.name == "nt":\n    pass',
    'windows = os.name != "posix"',
    'monkeypatch.setattr(interp, "_on_windows", lambda: True)',
    'monkeypatch.setattr(os, "getuid", lambda: 1000)',
    'monkeypatch.setattr(thing, "name", "nt")',
    'reason = f"os.name is {os.name}"',
    'note = "monkeypatch.setattr(os, \\"name\\", \\"nt\\") is what this file used to do"',
    'log("the value of os.name here", os.name)',
])
def test_reading_the_name_is_not_reported(statement):
    assert forcing_lines(statement) == []


def test_no_test_forces_os_name():
    found = {path.relative_to(TESTS).as_posix(): forcing_lines(path.read_text(encoding="utf-8"))
             for path in sorted(TESTS.rglob("*.py"))}
    found = {name: lines for name, lines in found.items() if lines}
    assert not found, f"these tests set os.name for the whole process: {found}"


@pytest.mark.parametrize("module", [interpreters, mission_identifier, terminal], ids=lambda module: module.__name__)
def test_the_function_a_test_replaces_reports_the_real_platform(module):
    assert module._on_windows() is (os.name == "nt")
