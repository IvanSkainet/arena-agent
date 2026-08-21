"""CodeQL #622/#625 -- `run_sd` handed attacker text to `cmd.exe` (Windows).

`make_run_sd` ran its Windows branch with `shell=True` and a `nosec`
saying "argv[0] is a fixed sd-exec binary path (no operator
interpolation)". The claim did not describe the code. Every Windows
caller passes argv the caller controls:

  * `browser.shot` -> `[chrome_exe, ..., url]`
  * `exec.run`     -> `["cmd", "/c", cmd]`

With `shell=True` Python joins the list with `list2cmdline` and gives
the single string to `cmd.exe`, which re-reads it for `&`, `|`, `>`.
`list2cmdline` quotes for the C runtime, not for a shell, and only when
an argument contains whitespace -- so a space-free URL carries its
payload straight through.

Verified on the operator's Windows host (Python 3.14.7), same argv shape
as `browser.shot`::

    evil = "http://x/?a=1&echo.PWNED>" + marker
    subprocess.run([sys.executable, "-c", "...", evil], shell=True)
    -> marker created
    subprocess.run([sys.executable, "-c", "...", evil], shell=False)
    -> marker not created

`browser.shot` does run `check_navigation` on the URL first, and that
policy (SSRF, #103) passes `&`, `|` and `>` through untouched -- it was
built to answer "may I reach this host", not "is this safe to paste
into a shell". Confirmed by executing it, not by reading it.

These tests do not require Windows: they pin the shape of the call.
A test that only ran on the affected platform would be skipped on every
machine that runs this suite, which is the same as not having it.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import subprocess
import sys

import pytest

from arena.mcp.tool_utils import make_run_sd

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "arena" / "mcp" / "tool_utils.py"


def _run_sd_calls() -> list[ast.Call]:
    """Every subprocess call inside `make_run_sd`."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "make_run_sd"
    )
    spawners = ("subprocess.run", "subprocess.Popen", "subprocess.call",
                "subprocess.check_call", "subprocess.check_output")
    return [
        n for n in ast.walk(func)
        if isinstance(n, ast.Call) and ast.unparse(n.func) in spawners
    ]


def test_run_sd_never_asks_for_a_shell():
    """The whole defect in one assertion."""
    for call in _run_sd_calls():
        for kw in call.keywords:
            if kw.arg == "shell":
                value = ast.unparse(kw.value)
                pytest.fail(
                    f"run_sd passes shell={value} at line {call.lineno}; "
                    "argv is caller-controlled on every Windows call site"
                )


def test_run_sd_still_passes_a_list_not_a_string():
    """`shell=False` with a joined string would re-open the same hole
    through a different door."""
    for call in _run_sd_calls():
        first = call.args[0]
        assert not isinstance(first, ast.JoinedStr), (
            f"line {call.lineno} builds a command string"
        )
        assert not (
            isinstance(first, ast.Call) and ast.unparse(first.func).endswith("join")
        ), f"line {call.lineno} joins argv into one string"


def test_no_suppression_survives_on_the_subprocess_lines():
    """A `nosec`/`nosemgrep` here would re-silence the finding.

    The old one claimed argv[0] was "a fixed sd-exec binary path (no
    operator interpolation)", which was never true of any Windows call
    site. Rather than pin that wording -- a comment can be reworded
    while staying just as wrong -- refuse suppressions on these lines
    outright. If one is ever genuinely needed, this test is the place to
    argue for it.
    """
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    for call in _run_sd_calls():
        for lineno in range(call.lineno, (call.end_lineno or call.lineno) + 1):
            text = lines[lineno - 1].lower()
            for marker in ("nosec", "nosemgrep", "noqa: s6", "type: ignore"):
                assert marker not in text, (
                    f"line {lineno} suppresses an analyser on a subprocess "
                    f"call: {lines[lineno - 1].strip()[:90]}"
                )


def test_the_docstring_does_not_reassert_the_false_claim():
    """The rationale that let this live from v4.44.0 to now."""
    body = inspect.getsource(make_run_sd)

    assert "no operator interpolation" not in body, (
        "that phrase described argv[0] as fixed; every Windows caller "
        "appends caller-controlled text"
    )


def test_the_windows_branch_and_the_posix_branch_agree_on_shape():
    """Both branches must hand subprocess a list."""
    calls = _run_sd_calls()
    assert len(calls) == 2, f"expected two subprocess calls, found {len(calls)}"
    for call in calls:
        first = call.args[0]
        assert isinstance(first, (ast.Name, ast.List, ast.BinOp)), (
            f"line {call.lineno} passes {type(first).__name__}"
        )


# --- the behaviour itself, on whatever platform is running -----------------

def test_a_metacharacter_in_an_argument_stays_an_argument(tmp_path):
    """The real proof: run it and see whether the payload fires.

    On Windows this fails against the old code and passes against the
    new. On POSIX `shell=True` would mangle argv differently but just as
    badly, so the same assertion holds; either way the argument must
    arrive whole.
    """
    marker = tmp_path / "pwned.txt"
    evil = f"http://x/?a=1&echo.PWNED>{marker}"

    seen = []

    def fake_kwargs():
        return {}

    run_sd = make_run_sd(bin_dir=str(tmp_path), subprocess_kwargs=fake_kwargs)

    real_run = subprocess.run

    def spy(argv, **kwargs):
        seen.append((argv, kwargs))
        return real_run(
            [sys.executable, "-c", "import sys; print(sys.argv[1])", evil],
            capture_output=True, text=True, timeout=30,
        )

    import arena.mcp.tool_utils as mod

    original = mod.subprocess.run
    mod.subprocess.run = spy
    try:
        rc, out, err = run_sd([sys.executable, "-c", "pass", evil], timeout=10)
    finally:
        mod.subprocess.run = original

    assert not marker.exists(), (
        "the shell executed the tail of the URL as a second command"
    )
    assert evil in out, f"the argument did not arrive intact: {out!r}"
    assert seen and "shell" not in seen[0][1], (
        f"run_sd asked for a shell: {seen[0][1]}"
    )


def test_the_navigation_policy_does_not_make_the_url_shell_safe():
    """Recorded because it is the tempting wrong fix.

    "browser.shot validates the URL first" is true and irrelevant: the
    SSRF policy answers a different question, and passes shell
    metacharacters straight through.
    """
    from arena.browser.navigation_policy import check_navigation

    hostile = "http://example.com/?a=1&whoami"

    assert check_navigation(hostile) == hostile, (
        "if the policy starts rejecting these, this test should be "
        "rewritten -- but run_sd must not rely on it either way"
    )
