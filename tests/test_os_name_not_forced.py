"""No test may change ``os.name`` for the whole process.

``os`` is one module object. A test that sets ``os.name`` changes it for every
library running in that process until the test ends: pytest, coverage,
``sysconfig``, ``pathlib``. coverage re-reads the ``sysconfig`` install paths
whenever ``sys.path`` has changed, at the moment it first sees a new file. When
that moment fell inside a test with ``os.name`` forced to ``"nt"`` on macOS,
``sysconfig`` raised and the pytest worker died with an INTERNALERROR.

A module that needs the answer asks a function of its own, ``_on_windows()``,
and a test replaces that function.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from arena.exec import interpreters
from arena.relay import terminal
from arena.resources import mission_identifier

TESTS = Path(__file__).resolve().parent

# setattr(os, "name", ...), setattr(module.os, "name", ...), setattr("os.name", ...), patch("os.name"),
# patch.object(os, "name"), and a plain assignment.
FORCED = re.compile(
    r"""(?:\b|\.)os\s*,\s*["']name["']"""
    r"""|["'](?:[\w.]+\.)?os\.name["']"""
    r"""|(?:\b|\.)os\.name\s*=(?!=)"""
)


def forcing_lines(text: str) -> list[int]:
    """Return the numbers of the lines that set ``os.name``."""
    return [number for number, line in enumerate(text.splitlines(), 1)
            if FORCED.search(line) and not line.lstrip().startswith("#")]


@pytest.mark.parametrize("line", [
    'monkeypatch.setattr(os, "name", "nt")',
    "monkeypatch.setattr(os, 'name', 'posix')",
    'monkeypatch.setattr(interp.os, "name", os_name)',
    'monkeypatch.setattr("os.name", "nt")',
    'monkeypatch.setattr("arena.exec.interpreters.os.name", "nt")',
    'with mock.patch("os.name", "nt"):',
    'with mock.patch.object(os, "name", "nt"):',
    'os.name = "nt"',
    'module.os.name = "nt"',
])
def test_every_way_of_forcing_is_recognised(line):
    assert forcing_lines(line) == [1]


@pytest.mark.parametrize("line", [
    'if os.name == "nt":',
    'windows = os.name != "posix"',
    'monkeypatch.setattr(interp, "_on_windows", lambda: True)',
    'monkeypatch.setattr(os, "getuid", lambda: 1000)',
    'reason = f"os.name is {os.name}"',
    '# monkeypatch.setattr(os, "name", "nt") is what this file used to do',
])
def test_reading_the_name_is_not_reported(line):
    assert forcing_lines(line) == []


def test_no_test_forces_os_name():
    found = {path.name: forcing_lines(path.read_text(encoding="utf-8"))
             for path in sorted(TESTS.rglob("*.py")) if path != Path(__file__).resolve()}
    found = {name: lines for name, lines in found.items() if lines}
    assert not found, f"these tests set os.name for the whole process: {found}"


@pytest.mark.parametrize("module", [interpreters, mission_identifier, terminal], ids=lambda module: module.__name__)
def test_the_function_a_test_replaces_reports_the_real_platform(module):
    assert module._on_windows() is (os.name == "nt")
