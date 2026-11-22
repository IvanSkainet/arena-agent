"""#528: the GuardDog gate keeps GuardDog off the network for package lists, and a stuck scan is short and named."""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "guarddog_gate.py"
CLEAN = '{"package": "aiohttp", "issues": 0, "results": {}}'
LONG_AGO = 1
NOW = 1_800_000_000


def _load():
    spec = importlib.util.spec_from_file_location("guarddog_gate_528", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Finished:
    stdout = CLEAN


@pytest.fixture(name="gate")
def _gate(monkeypatch):
    """A fresh copy of the gate, with a clock that stands still: it remembers the directory it made."""
    module = _load()
    monkeypatch.setattr(module.time, "time", lambda: NOW + 0.5)
    return module


@pytest.fixture(name="bundled")
def _bundled(tmp_path, monkeypatch):
    """An installed GuardDog whose lists are years old, as far as the gate can tell."""
    resources = tmp_path / "guarddog" / "analyzer" / "metadata" / "resources"
    resources.mkdir(parents=True)
    (tmp_path / "guarddog" / "__init__.py").write_text("raise ImportError('the gate must not import GuardDog')\n", encoding="utf-8")
    (resources / "top_pypi_packages.json").write_text(json.dumps({"downloaded_timestamp": LONG_AGO, "packages": ["requests"]}), encoding="utf-8")
    (resources / "top_go_packages.json").write_text(json.dumps(["an", "older", "format"]), encoding="utf-8")
    (resources / "placeholder_email_domains.txt").write_text("example.com\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "guarddog", raising=False)
    importlib.invalidate_caches()
    return resources


def test_the_lists_guarddog_is_given_look_fresh(gate, bundled):
    """Thirty days is GuardDog's limit; these are dated now, with the same packages."""
    listing = json.loads(Path(gate.dated_lists(), "top_pypi_packages.json").read_text(encoding="utf-8"))
    assert listing == {"downloaded_timestamp": NOW, "packages": ["requests"]}


def test_the_installed_lists_are_left_as_they_were(gate, bundled):
    """The copy is dated, not the original."""
    gate.dated_lists()
    assert json.loads((bundled / "top_pypi_packages.json").read_text(encoding="utf-8"))["downloaded_timestamp"] == LONG_AGO


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_the_copies_are_private(gate, bundled):
    """Owner only, whatever the umask."""
    modes = {stat.S_IMODE(path.stat().st_mode) for path in Path(gate.dated_lists()).iterdir()}
    assert modes == {0o600}


def test_only_the_package_lists_are_copied(gate, bundled):
    """A list in a format without a date is passed on unchanged; other resources are not lists."""
    copied = Path(gate.dated_lists())
    assert sorted(path.name for path in copied.iterdir()) == ["top_go_packages.json", "top_pypi_packages.json"]
    assert json.loads((copied / "top_go_packages.json").read_text(encoding="utf-8")) == ["an", "older", "format"]


def test_every_scan_is_pointed_at_those_lists_and_given_a_short_limit(gate, bundled, monkeypatch):
    """One directory for the whole run, not one per package."""
    calls = []
    monkeypatch.setattr(gate.subprocess, "run", lambda command, **options: calls.append(options) or _Finished())
    gate.scan("aiohttp")
    gate.scan("yarl")
    assert {options["env"][gate.LISTS_VARIABLE] for options in calls} == {gate.dated_lists()}
    assert {options["timeout"] for options in calls} == {gate.SCAN_TIMEOUT}
    assert gate.SCAN_TIMEOUT <= 300


def test_without_guarddog_the_variable_is_not_invented(gate, monkeypatch):
    """Nothing to copy: GuardDog's own failure to start is the error to report."""
    monkeypatch.setattr(gate.importlib.util, "find_spec", lambda name: None)
    assert gate.LISTS_VARIABLE not in gate.scan_environment()


def test_a_scan_that_does_not_finish_fails_the_gate(gate, monkeypatch, capsys):
    """An unscanned package is not a clean one, and the log says which package it was."""
    def stall(command, **options):
        raise gate.subprocess.TimeoutExpired(command, options["timeout"])

    monkeypatch.setattr(gate.subprocess, "run", stall)
    assert gate.check(["aiohttp"]) == 1
    captured = capsys.readouterr()
    assert "scanning aiohttp" in captured.out
    assert "did not finish within" in captured.err
