"""A failed mission must exit non-zero.

`mission_manager.py run <id>` printed `"ok": false`, wrote `state: "failed"`
into mission.json -- and exited 0. Three separate places dropped the outcome:

1. `_run_cmd_mission_orig` computed `ok` and returned nothing;
2. `run_cmd_mission` assigned that None to `_rc` and returned it;
3. `cli.main()` called `a.func(a)` for its side effects and returned nothing,
   and the `mission_manager.py` shim called `main()` without `SystemExit`.

Each layer on its own looks harmless, which is why it survived: the JSON on
stdout was always correct, so a human reading the output saw the failure. Only
a machine -- CI, a scheduler, another agent -- was misled, and those are
exactly the callers this CLI exists for.

Found by pylint's `assignment-from-no-return` while evaluating MegaLinter
(see docs/github_apps_actions_survey.md); 13 of its 6852 findings were
candidates for a real defect, and this was one of them.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from arena.missions_cli import commands as cmds  # noqa: E402


def _run_mission_with(monkeypatch, tmp_path, step_exit_code: int):
    """Drive the real run_cmd_mission against a mission whose step fails."""
    mdir = tmp_path / "demo"
    (mdir / "logs").mkdir(parents=True)
    (mdir / "mission.json").write_text(
        json.dumps({"id": "demo", "template": "custom", "state": "planned"}),
        encoding="utf-8")

    monkeypatch.setattr(cmds, "find_mission", lambda _id: mdir)
    monkeypatch.setattr(cmds, "commands_for", lambda _t: ["step-one"])
    monkeypatch.setattr(cmds, "report_cmd", lambda _a: None)
    monkeypatch.setattr(cmds, "run_cmd", lambda c, t: {
        "cmd": c, "exit_code": step_exit_code, "stdout": "", "stderr": ""})

    args = types.SimpleNamespace(id="demo", step=None, timeout=5)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmds.run_cmd_mission(args)
    state = json.loads((mdir / "mission.json").read_text(encoding="utf-8"))["state"]
    return rc, state, buf.getvalue()


def test_failed_mission_returns_nonzero(monkeypatch, tmp_path):
    rc, state, out = _run_mission_with(monkeypatch, tmp_path, step_exit_code=7)
    assert state == "failed", out
    assert '"ok": false' in out, out
    assert rc not in (None, 0), (
        f"mission reported failure but run_cmd_mission returned {rc!r}; "
        "a scripted caller would read that as success")


def test_successful_mission_returns_zero(monkeypatch, tmp_path):
    """The fix must not make every run look like a failure."""
    rc, state, out = _run_mission_with(monkeypatch, tmp_path, step_exit_code=0)
    assert state == "done", out
    assert rc == 0, rc


def test_worker_has_an_explicit_return():
    """Structural: `_run_cmd_mission_orig` must not fall off the end."""
    src = (REPO / "arena" / "missions_cli" / "commands.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_run_cmd_mission_orig")
    returns = [r for r in ast.walk(fn) if isinstance(r, ast.Return) and r.value is not None]
    assert returns, "the worker computes `ok` and must return it"


def test_cli_main_propagates_the_subcommand_result():
    """`main()` must return what the subcommand returned, not None."""
    src = (REPO / "arena" / "missions_cli" / "cli.py").read_text(encoding="utf-8")
    assert "return a.func(a)" in src, (
        "cli.main() calls the subcommand for side effects only; its exit code "
        "never reaches the shell")


def test_shim_raises_systemexit_with_the_code():
    src = (REPO / "scripts" / "mission_manager.py").read_text(encoding="utf-8")
    assert "raise SystemExit(main())" in src, (
        "the shim calls main() without propagating its return value")


@pytest.mark.skipif(not (REPO / "scripts" / "mission_manager.py").exists(),
                    reason="shim missing")
def test_shim_exits_nonzero_end_to_end(tmp_path):
    """The whole chain, run as a real process: unknown mission must fail."""
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "mission_manager.py"),
         "run", "definitely-not-a-real-mission-id"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
        # v4.169.9: this used to be a hand-built POSIX env. On Windows the
        # missing SYSTEMROOT killed the interpreter before it ran a line --
        # the process exited nonzero, so the assertion below passed for
        # entirely the wrong reason and the test proved nothing there.
        env={**os.environ, "HOME": str(tmp_path),
             "PYTHONPATH": str(REPO),
             "ARENA_AGENT_HOME": str(tmp_path / "arena-bridge")},
    )
    assert proc.returncode != 0, (
        f"running a nonexistent mission exited 0\nstdout={proc.stdout[:400]}\n"
        f"stderr={proc.stderr[:400]}")
