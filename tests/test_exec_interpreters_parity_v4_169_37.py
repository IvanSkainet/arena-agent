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
    "bash": {"cmd": "bash -euo pipefail {path}", "suffix": ".sh", "platform": "unix"},
    "sh": {"cmd": "sh -eu {path}", "suffix": ".sh", "platform": "unix"},
    "python": {"cmd": "python3 {path}", "suffix": ".py", "platform": "any",
               "cmd_win": "python {path}"},
    "python3": {"cmd": "python3 {path}", "suffix": ".py", "platform": "any",
                "cmd_win": "python {path}"},
    "node": {"cmd": "node {path}", "suffix": ".js", "platform": "any"},
    "pwsh": {"cmd": "pwsh -NoProfile -Command \"& '{path}'; exit $LASTEXITCODE\"",
             "suffix": ".ps1", "platform": "any", "quote": False},
    "powershell": {"cmd": "powershell -NoProfile -Command \"& '{path}'; exit $LASTEXITCODE\"",
                   "suffix": ".ps1", "platform": "win", "quote": False},
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
        assert config["platform"] in ("unix", "win", "any")
        if "cmd_win" in config:
            assert "{path}" in config["cmd_win"]


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


# --------------------------------------------------------------------
# Cross-platform availability (#247)
#
# python/python3/node were marked unix-only, so the bridge answered
# `400 interpreter 'python' not available on Windows` on hosts where
# python, python3, py and node are all on PATH. Refusing an installed
# interpreter is bad on its own; refusing *this* one pushed every script
# through PowerShell, whose quoting traps AGENTS.md documents at length.
# --------------------------------------------------------------------


@pytest.mark.parametrize("name", ["python", "python3", "node", "pwsh"])
def test_cross_platform_interpreters_run_on_both(name, monkeypatch):
    """Availability is decided by PATH, not by a hardcoded OS claim."""
    cfg = interp._INTERPRETERS[name]
    for os_name in ("nt", "posix"):
        monkeypatch.setattr(interp.os, "name", os_name)
        assert interp.interpreter_runs_here(cfg), (
            f"{name} is installed on both platforms; the table must not "
            f"refuse it on {os_name}"
        )


def test_posix_shells_are_still_refused_on_windows(monkeypatch):
    """The check must keep doing its real job."""
    monkeypatch.setattr(interp.os, "name", "nt")
    for name in ("bash", "sh"):
        assert not interp.interpreter_runs_here(interp._INTERPRETERS[name])


def test_powershell_is_still_refused_on_posix(monkeypatch):
    monkeypatch.setattr(interp.os, "name", "posix")
    assert not interp.interpreter_runs_here(interp._INTERPRETERS["powershell"])


def test_windows_python_does_not_invoke_python3(monkeypatch):
    """`python3` on Windows is an App Execution Alias, not the interpreter.

    A standard install puts a `python3.exe` stub in WindowsApps that can
    open the Microsoft Store instead of running the script. Windows must
    use `python`.
    """
    monkeypatch.setattr(interp.os, "name", "nt")
    for name in ("python", "python3"):
        cmd = interp.interpreter_command(interp._INTERPRETERS[name])
        assert cmd.startswith("python "), cmd
        assert "python3" not in cmd


def test_posix_python_still_uses_python3(monkeypatch):
    """On POSIX `python` may be absent or Python 2; python3 is correct."""
    monkeypatch.setattr(interp.os, "name", "posix")
    for name in ("python", "python3"):
        assert interp.interpreter_command(
            interp._INTERPRETERS[name]).startswith("python3 ")


# --------------------------------------------------------------------
# Native exit codes must survive PowerShell (#247)
#
# `powershell -File script.ps1` exits 0 unless the script itself calls
# `exit`, so a failing native command inside the script was reported as
# exit_code=0, ok=true -- a failed script indistinguishable from a
# successful one. Measured on the operator's Windows host:
#     -File                   -> 0   (wrong)
#     -Command + exit $LASTEXITCODE -> 3   (correct)
# bash never had this: it returns the last command's status, and `-e`
# aborts on the first failure.
# --------------------------------------------------------------------


@pytest.mark.parametrize("name", ["powershell", "pwsh"])
def test_powershell_propagates_native_exit_codes(name):
    cmd = interp._INTERPRETERS[name]["cmd"]
    assert "-Command" in cmd, "-File swallows the child's exit code"
    assert "exit $LASTEXITCODE" in cmd, (
        "without an explicit exit, a failing native command reports success"
    )


@pytest.mark.parametrize("name", ["powershell", "pwsh"])
def test_powershell_path_is_single_quoted_and_not_double_quoted(name):
    r"""`-Command "..."` cannot contain unescaped double quotes.

    _quote_path wraps in `"` on Windows; doing that inside the -Command
    string would produce `"& "C:\path"; exit ..."` and break the parse.
    These entries opt out and single-quote the path themselves -- literal
    in PowerShell, and a Windows path cannot contain a single quote.
    """
    cfg = interp._INTERPRETERS[name]
    assert cfg.get("quote") is False
    rendered = cfg["cmd"].format(path=interp.interpreter_path_arg(cfg, "C:\\x\\s.ps1"))
    assert "'C:\\x\\s.ps1'" in rendered
    assert '"C:' not in rendered, f"path was double-quoted inside -Command: {rendered}"


def test_non_powershell_interpreters_still_get_shell_quoting():
    """The opt-out must be narrow: everything else still needs quoting."""
    for name in ("bash", "sh", "python", "python3", "node"):
        cfg = interp._INTERPRETERS[name]
        assert cfg.get("quote") is not False, name
        arg = interp.interpreter_path_arg(cfg, "/tmp/a b/s.py")
        assert arg != "/tmp/a b/s.py", f"{name} lost its quoting"


def test_which_interpreter_still_resolves_the_executable():
    """The PATH check reads the first token; -Command must not break it."""
    for name, exe in (("powershell", "powershell"), ("pwsh", "pwsh"),
                      ("bash", "bash"), ("node", "node")):
        assert interp._INTERPRETERS[name]["cmd"].split()[0] == exe
