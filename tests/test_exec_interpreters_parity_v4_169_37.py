"""v4.169.37 -- arena.exec.interpreters parity tests (mutation-driven).

Pins every interpreter definition and path quoting behavior:
* `_INTERPRETERS` exact dictionary schema and entries (bash, sh, python, python3, node, pwsh, powershell);
* Default interpreter selection on Windows ("powershell") vs POSIX ("bash");
* `_quote_path` on Windows (double quotes) vs POSIX (shlex.quote);
* `_resolve_interpreter` case-insensitivity, whitespace stripping, and unknown fallback to None;
* `_which_interpreter` first-token binary lookup.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.exec.interpreters as interp  # noqa: E402

EXPECTED_INTERPRETERS = {
    "bash": {"cmd": "bash -euo pipefail {path}", "suffix": ".sh", "unix": True},
    "sh": {"cmd": "sh -eu {path}", "suffix": ".sh", "unix": True},
    "python": {"cmd": "python3 {path}", "suffix": ".py", "unix": True},
    "python3": {"cmd": "python3 {path}", "suffix": ".py", "unix": True},
    "node": {"cmd": "node {path}", "suffix": ".js", "unix": True},
    "pwsh": {"cmd": "pwsh -NoProfile -File {path}", "suffix": ".ps1", "unix": False},
    "powershell": {"cmd": "powershell -NoProfile -File {path}", "suffix": ".ps1", "unix": False},
}


# --------------------------------------------------------------------
# 1. Pinned Interpreter Table & Defaults
# --------------------------------------------------------------------
def test_interpreters_table_exact_parity():
    assert interp._INTERPRETERS == EXPECTED_INTERPRETERS
    for name, config in EXPECTED_INTERPRETERS.items():
        assert interp._INTERPRETERS[name] == config
        assert "{path}" in config["cmd"]
        assert isinstance(config["suffix"], str)
        assert isinstance(config["unix"], bool)


def test_default_constants():
    assert interp._DEFAULT_INTERPRETER_UNIX == "bash"
    assert interp._DEFAULT_INTERPRETER_WIN == "powershell"


# --------------------------------------------------------------------
# 2. _quote_path
# --------------------------------------------------------------------
def test_quote_path_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    assert interp._quote_path(r"C:\Program Files\script.py") == r'"C:\Program Files\script.py"'
    assert interp._quote_path("simple.sh") == '"simple.sh"'


def test_quote_path_posix(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    assert interp._quote_path("/path with spaces/script.sh") == "'/path with spaces/script.sh'"
    assert interp._quote_path("simple.sh") == "simple.sh"
    # Embedded single quotes escaped safely by shlex
    assert interp._quote_path("/path's/script.sh") == "'/path'\"'\"'s/script.sh'"


# --------------------------------------------------------------------
# 3. _resolve_interpreter
# --------------------------------------------------------------------
def test_resolve_interpreter_defaults(monkeypatch):
    # Windows default
    monkeypatch.setattr(os, "name", "nt")
    win_res = interp._resolve_interpreter("")
    assert win_res == ("powershell", EXPECTED_INTERPRETERS["powershell"])

    # POSIX default
    monkeypatch.setattr(os, "name", "posix")
    posix_res = interp._resolve_interpreter("")
    assert posix_res == ("bash", EXPECTED_INTERPRETERS["bash"])


@pytest.mark.parametrize("name", ["bash", "sh", "python", "python3", "node", "pwsh", "powershell"])
def test_resolve_interpreter_exact_and_case_insensitive(name):
    # exact
    assert interp._resolve_interpreter(name) == (name, EXPECTED_INTERPRETERS[name])
    # uppercase and whitespace
    assert interp._resolve_interpreter(f"  {name.upper()}  ") == (name, EXPECTED_INTERPRETERS[name])


def test_resolve_interpreter_unknown():
    assert interp._resolve_interpreter("ruby") is None
    assert interp._resolve_interpreter("unknown_lang") is None


# --------------------------------------------------------------------
# 4. _which_interpreter
# --------------------------------------------------------------------
def test_which_interpreter_resolves_first_token(monkeypatch):
    seen_which_arg = []

    def _mock_which(binary):
        seen_which_arg.append(binary)
        if binary == "bash":
            return "/bin/bash"
        return None

    monkeypatch.setattr(shutil, "which", _mock_which)
    assert interp._which_interpreter("bash -euo pipefail {path}") == "/bin/bash"
    assert seen_which_arg == ["bash"]


def test_which_interpreter_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda binary: None)
    assert interp._which_interpreter("nonexistent_binary --flag {path}") is None
