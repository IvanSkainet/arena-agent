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


# --- run_local: argv[0] is a different question entirely -------------------

def test_run_local_refuses_a_program_that_is_not_ours():
    """Arguments may come from anywhere; argv[0] may not.

    Without a shell, a caller-supplied *argument* is handed to the child
    untouched -- that is the whole fix above. A caller-supplied
    *program* is another matter: it chooses what executes, and no
    quoting helps. Every real caller passes `sys.executable` or a path
    under the interpreter's directory, so this was already true by
    convention. Conventions do not survive refactors.
    """
    from arena.mcp.tool_utils import UntrustedProgram, _require_trusted_program

    for hostile in (["/bin/sh", "-c", "id"],
                    ["/usr/bin/chromium", "--headless"],
                    ["cmd", "/c", "dir"],
                    []):
        with pytest.raises(UntrustedProgram):
            _require_trusted_program(hostile)


def test_a_program_is_ours_by_directory_not_by_name(tmp_path):
    """Review (Sourcery) caught this and was right.

    The first version accepted any basename starting with `python` or
    `py_`. That is not a property of our tree: `/tmp/python`,
    `./python_backdoor` and `/tmp/py_evil` all matched. Verified against
    the old code -- all four were accepted. What makes a program ours is
    the directory it lives in.
    """
    from arena.mcp.tool_utils import UntrustedProgram, _require_trusted_program

    for name in ("python", "python3", "py_evil", "python_backdoor"):
        planted = tmp_path / name
        planted.write_text("#!/bin/sh\nid\n", encoding="utf-8")
        with pytest.raises(UntrustedProgram):
            _require_trusted_program([str(planted)])


def test_the_installed_bin_dir_is_trusted_when_given(tmp_path):
    """`py_browser.py` and `agentctl` live in the install tree's `bin/`,
    which is not under the interpreter's directory -- so the guard has
    to be told about it, or every browser tool breaks."""
    import os

    from arena.mcp.tool_utils import UntrustedProgram, _require_trusted_program

    bin_dir = tmp_path / "arena-bridge" / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("py_browser.py", "agentctl", "hooks_runner.py"):
        (bin_dir / name).write_text("x", encoding="utf-8")
        _require_trusted_program([str(bin_dir / name)], str(bin_dir))

    # ...and being told about one directory does not open the parent.
    outsider = tmp_path / "arena-bridge" / "py_browser.py"
    outsider.write_text("x", encoding="utf-8")
    with pytest.raises(UntrustedProgram):
        _require_trusted_program([str(outsider)], str(bin_dir))

    assert os.path.exists(outsider)


def test_a_sibling_directory_is_not_inside_the_trusted_one(tmp_path):
    """Sabotage caught this: `startswith` is not path containment.

    `/usr/local/bin-evil` starts with `/usr/local/bin`, so a prefix
    comparison admits a directory that merely shares a name prefix with
    the trusted one -- an attacker who can create a sibling gets a free
    pass. `os.path.commonpath` compares components, which is the
    question actually being asked.
    """
    from arena.mcp.tool_utils import UntrustedProgram, _require_trusted_program

    trusted = tmp_path / "bin"
    trusted.mkdir()
    sibling = tmp_path / "bin-evil"
    sibling.mkdir()
    planted = sibling / "python3"
    planted.write_text("x", encoding="utf-8")

    with pytest.raises(UntrustedProgram):
        _require_trusted_program([str(planted)], str(trusted))


def test_the_trusted_directory_itself_is_not_a_program(tmp_path):
    """Passing the directory as argv[0] must not satisfy the guard."""
    from arena.mcp.tool_utils import UntrustedProgram, _require_trusted_program

    trusted = tmp_path / "bin"
    trusted.mkdir()

    with pytest.raises(UntrustedProgram):
        _require_trusted_program([str(trusted)], str(trusted))


def test_the_bin_dir_is_actually_wired_through():
    """A parameter nobody passes is a parameter that does nothing."""
    import inspect

    from arena.mcp import standalone_common, tools

    assert "bin_dir=BIN" in inspect.getsource(standalone_common).replace(" ", "").replace(
        "bin_dir=BIN", "bin_dir=BIN")
    wired = inspect.getsource(tools)
    assert "make_run_local(ctx.subprocess_kwargs, bin_dir=ctx.bin_dir)" in wired


def test_run_local_still_accepts_every_shape_the_tree_uses():
    """The guard is worthless if it breaks the real callers."""
    import os

    from arena.mcp.tool_utils import _require_trusted_program

    bin_dir = os.path.dirname(sys.executable)
    for ours in ([sys.executable, "-c", "pass"],
                 [sys.executable, os.path.join("bin", "py_browser.py"), "search"],
                 [os.path.join(bin_dir, "agentctl"), "sys", "status"]):
        _require_trusted_program(ours)

    # A bare relative name is refused on purpose: it resolves against
    # whatever the working directory happens to be, which is not a
    # location this project controls. Every real call site builds an
    # absolute path from `BIN` or uses `sys.executable`.
    from arena.mcp.tool_utils import UntrustedProgram

    with pytest.raises(UntrustedProgram):
        _require_trusted_program(["py_browser.py"])


def test_the_guard_runs_before_the_process_starts():
    """A check that is defined but never called is decoration."""
    from arena.mcp.tool_utils import make_run_local

    source = inspect.getsource(make_run_local)

    at_guard = source.index("_require_trusted_program(argv")
    at_run = source.index("subprocess.run(")
    assert at_guard < at_run, "the guard must precede the spawn"
