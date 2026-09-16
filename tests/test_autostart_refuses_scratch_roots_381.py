"""`service.autostart_repair` must not aim autostart at a tmpdir (#381).

`repair()` resolves its install root from `ARENA_AGENT_HOME`. The
dispatch contract test calls every declared MCP tool -- this one
included -- under a fixture that points that variable at
`tempfile.mkdtemp()`. On the reporting machine a full local run
therefore replaced the operator's real Scheduled Task with one aimed at
a pytest temporary directory:

    Task To Run: wscript.exe "C:\\...\\Temp\\mcp-dispatch-71p201b0\\start_hidden.vbs"

The directory was gone by the next boot. Windows then runs `wscript`
against a missing script at every logon, `wscript` starts successfully,
and the task reports Last Result 0 -- so autostart is dead while every
layer claims success.

Two independent defects, tested separately:

* the resolved root is trusted without question, so a scratch directory
  becomes the install target;
* `repair()` deletes the existing task *before* discovering the
  replacement is unusable, leaving the machine worse off than if the
  repair had never run.
"""
from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import pytest

from arena.service import autostart_doctor

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCTOR = REPO_ROOT / "arena" / "service" / "autostart_doctor.py"


def test_a_pytest_tmpdir_is_rejected_as_an_install_root(
        tmp_path: Path) -> None:
    """The exact directory shape that broke the reporting machine.

    Built under `tmp_path` rather than with a bare `mkdtemp`, which
    leaked a directory into the host temp area on every run (review) --
    the same litter that made `%TEMP%` on the reporting machine hold
    221 of them.
    """
    scratch = (tmp_path / "mcp-dispatch-71p201b0")
    scratch.mkdir()
    scratch = scratch.resolve()

    reason = autostart_doctor._looks_like_a_scratch_root(scratch)

    assert reason, (
        f"{scratch} is a pytest temporary directory and was accepted as an "
        "autostart install root")


def test_the_temp_root_itself_is_rejected() -> None:
    """A control for the check above, one level up."""
    assert autostart_doctor._looks_like_a_scratch_root(
        Path(tempfile.gettempdir()).resolve())


@pytest.mark.parametrize("root", [
    Path("/opt/arena-bridge"),
    Path.home() / "arena-bridge",
    # Reads like scratch, is not: the first version matched the prefix
    # as a bare substring and refused this (review). `mkdtemp` appends
    # eight random characters; a deliberate name does not.
    Path("/home/user/mcp-dispatch-production"),
])
def test_a_real_install_path_is_not_rejected(root: Path) -> None:
    """The guard must not refuse ordinary installs.

    Without this, "reject everything" would satisfy the tests above
    while breaking the repair for every legitimate caller.
    """
    assert not autostart_doctor._looks_like_a_scratch_root(root.resolve())


def test_repair_refuses_before_deleting_the_existing_task(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Order matters more than the refusal itself.

    The old code ran `schtasks /Delete /TN ... /F` and only then found
    out the new target was wrong. A repair that destroys a working task
    and installs a broken one is worse than no repair, so the refusal
    has to come first.
    """
    scratch = tmp_path / "mcp-dispatch-71p201b0"
    scratch.mkdir()
    ran: list[list[str]] = []

    monkeypatch.setattr(autostart_doctor.platform, "system", lambda: "Windows")
    monkeypatch.setenv("ARENA_AGENT_HOME", scratch)
    monkeypatch.setattr(
        autostart_doctor, "_run",
        lambda cmd, timeout=10: ran.append(list(cmd)) or {"ok": True})

    result = autostart_doctor.repair()

    assert result["ok"] is False, result
    assert "refusing" in result["error"], result
    assert ran == [], (
        f"repair ran {ran} before refusing; any scheduler call here "
        "replaces the operator's working task")


def test_no_scheduler_call_precedes_the_refusals() -> None:
    """Structural backstop for the ordering above.

    The behavioural test drives the Windows branch with `platform.system`
    patched, which is the right check but is easy to render vacuous by a
    refactor that moves the delete somewhere the patch does not reach.
    This reads the source instead: inside `repair`, no `schtasks`
    invocation may appear before the guard that can refuse.
    """
    tree = ast.parse(DOCTOR.read_text(encoding="utf-8"))
    # The Windows arm lives in its own function; `repair()` only
    # dispatches to it. Look wherever the schtasks calls actually are,
    # so moving them again does not quietly skip this check.
    func = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef)
         and _first_line_calling(n, "_looks_like_a_scratch_root") is not None),
        None)
    assert func is not None, (
        "no function calls the scratch-root guard any more -- if the repair "
        "moved, point this check at its new home rather than deleting it")

    guard_line = _first_line_calling(func, "_looks_like_a_scratch_root")
    schtasks_line = _first_line_mentioning(func, "schtasks")

    assert guard_line is not None, (
        "nothing checks whether the root is a scratch directory")
    assert schtasks_line is not None, "no schtasks call found"
    assert guard_line < schtasks_line, (
        f"the scratch-root guard is at line {guard_line} but the first "
        f"scheduler call runs at line {schtasks_line}; the operator's task "
        "is replaced before the target is validated")


def _first_line_calling(func: ast.AST, name: str) -> int | None:
    """Line of the first call to `name` inside `func`."""
    lines = [
        node.lineno for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", "")) == name
    ]
    return min(lines) if lines else None


def _first_line_mentioning(func: ast.AST, needle: str) -> int | None:
    """Line of the first string constant containing `needle`."""
    lines = [
        node.lineno for node in ast.walk(func)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str) and needle in node.value
    ]
    return min(lines) if lines else None


def test_repair_refuses_when_the_launcher_is_missing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The second refusal, and it was untested until a mutation said so.

    Removing the `vbs.is_file()` check left every other test passing --
    a guard with no test is a guard that will be deleted by the next
    refactor. A task pointing at a missing script is exactly the state
    the reporting machine was found in: `wscript` starts, Last Result is
    0, nothing launches.
    """
    # `tmp_path` lives under the temp root and would trip the scratch
    # guard first, so that guard is stubbed out: this test is about the
    # *launcher* check, and a fixed path under $HOME risked reusing a
    # directory a previous run had populated (review).
    ran: list[list[str]] = []
    monkeypatch.setattr(autostart_doctor.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        autostart_doctor, "_looks_like_a_scratch_root", lambda root: "")
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(
        autostart_doctor, "_run",
        lambda cmd, timeout=10: ran.append(list(cmd)) or {"ok": True})
    # Launchers "written" successfully, but nothing on disk.
    monkeypatch.setattr(
        autostart_doctor, "write_windows_launchers",
        lambda root, **kw: {"ok": True, "created": []})
    monkeypatch.setattr(
        autostart_doctor, "repair_bare_python", lambda root: {"ok": True})

    result = autostart_doctor.repair()

    assert result["ok"] is False, result
    assert "missing or not a regular file" in result["error"], result
    assert ran == [], (
        f"repair ran {ran} before noticing the launcher was missing; any "
        "scheduler call here replaces the operator's working task")
