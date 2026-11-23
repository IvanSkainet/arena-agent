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
#
# The guard reads the syntax tree and reports the direct forms: setattr and patch
# calls, and statements that bind ``os.name``. It is a tripwire, not a proof: a
# write through ``vars(os)`` or ``os.__dict__`` is not reported.
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
    # Positional and keyword arguments alike: setattr(os, name="name", value="nt") is the same call.
    given = [*call.args, *(keyword.value for keyword in call.keywords)]
    if any(DOTTED.search(_text(value)) for value in given):
        return True
    return any(_is_os(value) for value in given) and any(_text(value) == "name" for value in given)


def _leaves(target: ast.AST) -> list[ast.AST]:
    """Return what a target assigns to, with tuples, lists and stars opened up."""
    if isinstance(target, (ast.Tuple, ast.List)):
        return [leaf for element in target.elts for leaf in _leaves(element)]
    return _leaves(target.value) if isinstance(target, ast.Starred) else [target]


def _targets(node: ast.AST) -> list[ast.AST]:
    """Return the targets of a statement that binds: assignment, ``for`` and ``with ... as``."""
    if isinstance(node, ast.Assign):
        return node.targets
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return [item.optional_vars for item in node.items if item.optional_vars is not None]
    return [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.For, ast.AsyncFor)) else []


def _assigned(node: ast.AST) -> list[ast.AST]:
    """Return every single place a statement assigns to."""
    return [leaf for target in _targets(node) for leaf in _leaves(target)]


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
    'monkeypatch.setattr(os, name="name", value="nt")',
    'monkeypatch.setattr(target=os, name="name", value="nt")',
    'mock.patch(target="os.name", new="nt")',
    'os.name, sys.platform = "nt", "win32"',
    '[sys.platform, (other, os.name)] = "win32", ("x", "nt")',
    'first, *os.name = "a", "n", "t"',
    'for os.name in ("nt", "posix"):\n    pass',
    'with manager() as os.name:\n    pass',
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
    'name, platform = os.name, sys.platform',
    'for name in (os.name, "posix"):\n    pass',
    'with open(os.devnull) as name:\n    pass',
    'monkeypatch.setattr(sys, name="platform", value="win32")',
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
