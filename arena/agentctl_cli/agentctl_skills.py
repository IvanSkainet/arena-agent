"""agentctl skill commands."""
from __future__ import annotations

import json
import os
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
    if runner_sh.exists():
        _run_skill_process(["bash", str(runner_sh)] + skill_args, name, skill_dir, skill_args)
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
