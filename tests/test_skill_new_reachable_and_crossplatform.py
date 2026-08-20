"""`skill new` must be reachable, and scaffolded skills must run on Windows.

Regression guard for the remaining half of #126.

Three defects, all in the "documented feature that cannot be invoked" family:

1. `new` was absent from `DISPATCH["skill"]`, so `agentctl skill new core/x`
   never reached the scaffolder. (Before #141 it silently ran `skill list`
   and exited 0; after #141 it was correctly refused - but still absent.)
2. `arena/skills/cli.py` had no `if __name__ == "__main__":` guard, so
   `python -m arena.skills.cli new core/x` executed the module body,
   created nothing and exited 0.
3. `cli_new.py` scaffolded only `run.sh` with a bash shebang. Windows is a
   supported platform with no bash on PATH, and the CLI runner tried `run.sh`
   *before* `run.py` and then `sys.exit`ed - so a skill shipping both runners
   died on the missing bash and never reached its Python entry point.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[1]

from arena.agentctl_cli import agentctl_main, agentctl_skills  # noqa: E402


@pytest.fixture
def skills_home(tmp_path, monkeypatch):
    """Point the skills CLI at an empty tree under tmp_path."""
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    (tmp_path / "skills").mkdir()
    monkeypatch.setattr(agentctl_skills, "ROOT", tmp_path)
    import arena.skills.cli_common as cli_common
    import arena.skills.cli_new as cli_new

    monkeypatch.setattr(cli_common, "ROOT", tmp_path)
    monkeypatch.setattr(cli_common, "SK", tmp_path / "skills")
    monkeypatch.setattr(cli_new, "SK", tmp_path / "skills")
    return tmp_path


# --- 1. reachability through agentctl -------------------------------------


def test_skill_new_is_registered_in_the_dispatch_table():
    assert "new" in agentctl_main.DISPATCH["skill"], (
        "`agentctl skill new` is documented but absent from DISPATCH"
    )


def test_help_lists_the_new_subcommand(capsys):
    agentctl_main.commands([])
    out = capsys.readouterr().out
    assert "list|run|new" in out, "help must advertise a command it accepts"


def test_agentctl_skill_new_scaffolds_through_the_dispatcher(skills_home, monkeypatch, capsys):
    """The whole path, argv -> dispatcher -> scaffolder.

    The scaffolder is argparse-driven (`args.name`) while agentctl hands each
    command a list, so this asserts the adapter actually bridges the two -
    a test calling `new_skill` directly would not.
    """
    monkeypatch.setattr(sys, "argv", ["agentctl", "skill", "new", "core/demo"])

    with pytest.raises(SystemExit) as excinfo:
        agentctl_main.main()

    assert excinfo.value.code == 0
    created = skills_home / "skills" / "core" / "demo"
    assert (created / "SKILL.md").exists()
    assert (created / "manifest.json").exists()
    assert "scaffolded skill" in capsys.readouterr().out


def test_agentctl_skill_new_without_a_name_refuses(skills_home, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["agentctl", "skill", "new"])

    with pytest.raises(SystemExit) as excinfo:
        agentctl_main.main()

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "", "a usage error must not go to stdout"
    assert captured.err.splitlines() == [
        "Usage: agentctl skill new <namespace>/<name>  (e.g. core/digest)"
    ]


def test_agentctl_skill_new_rejects_a_name_without_a_namespace(skills_home, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["agentctl", "skill", "new", "nonamespace"])

    with pytest.raises(SystemExit) as excinfo:
        agentctl_main.main()

    assert excinfo.value.code == 2
    assert not list((skills_home / "skills").iterdir())


def test_agentctl_skill_new_is_idempotent_and_refuses_to_overwrite(skills_home, monkeypatch):
    from arena.skills.cli_new import new_skill

    assert new_skill(Namespace(name="core/demo")) == 0
    marker = skills_home / "skills" / "core" / "demo" / "SKILL.md"
    marker.write_text("edited by hand", encoding="utf-8")

    assert new_skill(Namespace(name="core/demo")) == 1
    assert marker.read_text(encoding="utf-8") == "edited by hand", (
        "a second scaffold must not clobber existing work"
    )


# --- 2. `python -m arena.skills.cli` --------------------------------------


def test_module_entry_point_actually_runs(tmp_path):
    """`python -m arena.skills.cli new ...` must scaffold, not no-op.

    Runs in a subprocess: the missing `__main__` guard is only observable
    when the module is executed as `__main__`, which an in-process import
    cannot reproduce.
    """
    # Inherit the real environment: a stripped env drops SYSTEMROOT and
    # CPython cannot even start on Windows.
    env = {
        **os.environ,
        "ARENA_AGENT_HOME": str(tmp_path),
        "PYTHONPATH": str(REPO_ROOT),
    }
    (tmp_path / "skills").mkdir()

    proc = subprocess.run(
        [sys.executable, "-m", "arena.skills.cli", "new", "core/via_module"],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(REPO_ROOT),
    )

    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "skills" / "core" / "via_module" / "SKILL.md").exists(), (
        f"module entry point created nothing; stdout={proc.stdout!r}"
    )


def test_module_entry_point_reports_a_bad_name(tmp_path):
    # Inherit the real environment: a stripped env drops SYSTEMROOT and
    # CPython cannot even start on Windows.
    env = {
        **os.environ,
        "ARENA_AGENT_HOME": str(tmp_path),
        "PYTHONPATH": str(REPO_ROOT),
    }
    (tmp_path / "skills").mkdir()

    proc = subprocess.run(
        [sys.executable, "-m", "arena.skills.cli", "new", "nonamespace"],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(REPO_ROOT),
    )

    assert proc.returncode == 2
    assert not any((tmp_path / "skills").iterdir())


# --- 3. cross-platform scaffold + runner order -----------------------------


def test_scaffold_emits_a_python_runner_not_a_bash_one(skills_home):
    from arena.skills.cli_new import new_skill

    new_skill(Namespace(name="core/demo"))
    created = skills_home / "skills" / "core" / "demo"

    assert (created / "run.py").exists(), "scaffold must be runnable on stock Windows"
    assert not (created / "run.sh").exists(), (
        "a bash runner alongside run.py resurrects the Windows failure"
    )


def test_scaffolded_runner_executes(skills_home):
    """The template must be valid Python, not just present."""
    from arena.skills.cli_new import new_skill

    new_skill(Namespace(name="core/demo"))
    runner = skills_home / "skills" / "core" / "demo" / "run.py"

    proc = subprocess.run(
        [sys.executable, str(runner), "alpha", "beta"],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "SKILL_NAME": "core/demo"},
    )

    assert proc.returncode == 0, proc.stderr
    assert "core/demo" in proc.stdout
    assert "alpha beta" in proc.stdout


def test_scaffolded_manifest_is_valid_json_naming_the_skill(skills_home):
    from arena.skills.cli_new import new_skill

    new_skill(Namespace(name="core/demo"))
    manifest = json.loads(
        (skills_home / "skills" / "core" / "demo" / "manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["name"] == "core/demo"
    assert manifest["mode"] == "safe"


def _stub_runner(monkeypatch):
    """Record the command and stop, as the real helper does via sys.exit."""
    seen: list[list[str]] = []

    def fake(cmd, name, skill_dir, skill_args):
        seen.append(list(cmd))
        raise SystemExit(0)

    monkeypatch.setattr(agentctl_skills, "_run_skill_process", fake)
    return seen


@pytest.mark.parametrize(
    ("platform", "expected_runner"),
    [("win32", "run.py"), ("linux", "run.sh")],
)
def test_runner_preference_matches_the_server_side_runner(
    skills_home, monkeypatch, platform, expected_runner
):
    """A skill shipping both runners must pick run.py on Windows.

    `arena/skills/runner.py:78` already prefers run.py on win32; the CLI tried
    run.sh first on every platform and then exited, so the Python entry point
    was unreachable on Windows.
    """
    both = skills_home / "skills" / "core" / "both"
    both.mkdir(parents=True)
    (both / "run.sh").write_text("#!/usr/bin/env bash\necho sh\n", encoding="utf-8")
    (both / "run.py").write_text("print('py')\n", encoding="utf-8")

    seen = _stub_runner(monkeypatch)
    looked_up: list[str] = []
    monkeypatch.setattr(
        agentctl_skills.shutil, "which",
        lambda cmd: (looked_up.append(cmd), "/usr/bin/bash")[1],
    )
    monkeypatch.setattr(sys, "platform", platform)

    with pytest.raises(SystemExit):
        agentctl_skills.run_skill(["core/both"])

    assert seen, "no runner was invoked"
    argv = seen[0]
    assert Path(argv[1]).name == expected_runner
    if expected_runner == "run.py":
        # Must be this interpreter, not a bare "python3" that may be absent
        # or be a different version than the one running agentctl.
        assert argv[0] == sys.executable
        assert looked_up == [], "no bash lookup is needed when run.py wins"
    else:
        assert argv[0] == "/usr/bin/bash"
        assert looked_up == ["bash"], f"resolved the wrong executable: {looked_up}"


def test_windows_runner_falls_back_when_sys_executable_is_empty(skills_home, monkeypatch):
    """A frozen or embedded interpreter reports sys.executable == "".

    The fallback must name a real command; spawning "" would fail with a
    confusing OSError instead of running the skill.
    """
    both = skills_home / "skills" / "core" / "both"
    both.mkdir(parents=True)
    (both / "run.py").write_text("print('py')\n", encoding="utf-8")

    seen = _stub_runner(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", "")

    with pytest.raises(SystemExit):
        agentctl_skills.run_skill(["core/both"])

    assert seen, "no runner was invoked"
    assert seen[0][0] == "python3", "empty sys.executable must fall back to python3"
    assert Path(seen[0][1]).name == "run.py"


def test_missing_bash_reports_instead_of_raising_winerror(skills_home, monkeypatch, capsys):
    """A .sh-only skill without bash must fail with a readable message.

    Previously this reached `subprocess.run(["bash", ...])` and surfaced as
    `Error running skill: [WinError 2]`, which names neither bash nor the
    skill.
    """
    sh_only = skills_home / "skills" / "core" / "shonly"
    sh_only.mkdir(parents=True)
    (sh_only / "run.sh").write_text("#!/usr/bin/env bash\necho sh\n", encoding="utf-8")

    seen = _stub_runner(monkeypatch)
    monkeypatch.setattr(agentctl_skills.shutil, "which", lambda _cmd: None)

    with pytest.raises(SystemExit) as excinfo:
        agentctl_skills.run_skill(["core/shonly"])

    assert excinfo.value.code == 1
    assert seen == [], "nothing may be executed when bash is unavailable"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == [
        "bash not available - .sh skills require WSL or Git Bash on Windows"
    ]


def test_scaffold_then_run_round_trip(skills_home, monkeypatch):
    """End to end: what `skill new` produces is what `skill run` can execute."""
    from arena.skills.cli_new import new_skill

    new_skill(Namespace(name="core/roundtrip"))

    seen = _stub_runner(monkeypatch)
    with pytest.raises(SystemExit):
        agentctl_skills.run_skill(["core/roundtrip"])

    assert seen, "the scaffolded skill was not runnable"
    assert Path(seen[0][1]).name == "run.py"
