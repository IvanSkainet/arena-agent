"""agentctl skill commands."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from arena.agentctl_cli.agentctl_common import ROOT, bridge_get, bridge_post


def list_skills(args):
    try:
        r = bridge_get("/v1/skills")
        print(f"Skills ({r.get('count',0)}):")
        for skill in r.get("skills", []):
            print(f"  {skill.get('name','?'):40s} {skill.get('description', '')[:50]}")
    except Exception as e:
        print(f"Error: {e}")


def new_skill(args):
    """Scaffold a new skill.

    `arena.skills.cli_new.new_skill` is argparse-driven and reads `args.name`,
    while agentctl hands each command a plain list, so the two cannot be wired
    together directly - which is part of why `skill new` was never reachable
    (#126). This adapts the list to the Namespace the scaffolder expects.
    """
    if len(args) != 1:
        # Extra words are a typo, not a flag set: accepting them silently
        # would scaffold core/x and drop the rest on the floor.
        detail = "" if not args else f": unexpected extra arguments {args[1:]}"
        print(f"Usage: agentctl skill new <namespace>/<name>  (e.g. core/digest){detail}",
              file=sys.stderr)
        sys.exit(2)
    from argparse import Namespace

    from arena.skills.cli_new import new_skill as _scaffold

    sys.exit(_scaffold(Namespace(name=args[0])) or 0)


def _resolve_skill_dir(name: str):
    skill_dir = ROOT / "skills" / name
    if skill_dir.exists():
        return skill_dir
    skills_root = ROOT / "skills"
    if not skills_root.exists():
        return skill_dir
    for subdir in skills_root.iterdir():
        if subdir.is_dir() and subdir.name == name:
            return subdir
    for subdir in skills_root.rglob(name):
        if subdir.is_dir() and any((subdir / n).exists() for n in ("run.sh", "run.py", "SKILL.md")):
            return subdir
    return skill_dir


def _run_skill_process(cmd: list[str], name: str, skill_dir, skill_args: list[str]) -> None:
    env = os.environ.copy()
    env.update({"ARENA_AGENT_HOME": str(ROOT), "SKILL_NAME": name, "SKILL_DIR": str(skill_dir),
                "SKILL_ARGS": json.dumps(skill_args)})
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        sys.exit(result.returncode)
    except subprocess.TimeoutExpired:
        print("Skill timed out (300s)", file=sys.stderr)
        sys.exit(124)
    except Exception as e:
        print(f"Error running skill: {e}", file=sys.stderr)
        sys.exit(1)


def run_skill(args):
    if not args:
        print("Usage: agentctl skill run <name> [args...]")
        sys.exit(2)
    name, skill_args = args[0], args[1:]
    skill_dir = _resolve_skill_dir(name)
    if not skill_dir.exists():
        try:
            r = bridge_post("/v1/skills/run", {"name": name, "args": skill_args})
            print(r.get("output", "") or r.get("stdout", ""), end="")
            if r.get("stderr"):
                print(r.get("stderr"), end="", file=sys.stderr)
            if not r.get("ok"):
                sys.exit(r.get("exit_code", 1))
            return
        except Exception:
            pass
        print(f"Skill not found: {name}")
        sys.exit(1)
    runner_sh, runner_py, skill_md = skill_dir / "run.sh", skill_dir / "run.py", skill_dir / "SKILL.md"
    # run.sh used to be tried first unconditionally, and _run_skill_process
    # ends in sys.exit - so on Windows a skill shipping both runners died on
    # the missing bash and never reached its run.py. The server-side runner
    # (arena/skills/runner.py:78) already prefers run.py on win32; match it.
    if sys.platform == "win32" and runner_py.exists():
        _run_skill_process([sys.executable or "python3", str(runner_py)] + skill_args, name, skill_dir, skill_args)
    if runner_sh.exists():
        bash = shutil.which("bash")
        if not bash:
            print("bash not available - .sh skills require WSL or Git Bash on Windows",
                  file=sys.stderr)
            sys.exit(1)
        _run_skill_process([bash, str(runner_sh)] + skill_args, name, skill_dir, skill_args)
    if runner_py.exists():
        _run_skill_process([sys.executable or "python3", str(runner_py)] + skill_args, name, skill_dir, skill_args)
    if skill_md.exists():
        try:
            print(f"[Prompt-only skill: {name}]\nLocation: {skill_dir}\n---")
            print(skill_md.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Error reading skill: {e}", file=sys.stderr)
            sys.exit(1)
        return
    print(f"No run.sh, run.py, or SKILL.md found in {skill_dir}")
    sys.exit(1)
