#!/usr/bin/env python3
"""
skill_runner.py — Arena Agent skills v0.1

A skill is a directory under ~/arena-bridge/skills/<namespace>/<name>/ with:

  SKILL.md      — human-readable description (purpose, inputs, outputs)
  run.sh        — optional executable; called as `bash run.sh "$@"`
  run.py        — optional executable; called as `python run.py "$@"`
                  (if both present, run.sh wins)
  manifest.json — optional metadata:
                    {
                      "name": "core/digest",
                      "description": "...",
                      "args": [{"name": "out", "required": false}],
                      "timeout": 300,
                      "mode": "safe|edit|full"   # advisory
                    }

Commands:
  list                       — list all skills (namespace/name)
  show <name>                — print SKILL.md
  run  <name> [args...]      — execute run.sh or run.py with args
  new  <namespace/name>      — scaffold a new skill
  path <name>                — print absolute path of skill dir

The existing `agentctl skill-list` / `skill-show` (superpowers_lite.py) keep
working — they only read markdown files. This module is the *executor* layer
and shares the same ~/arena-bridge/skills/ directory.

Output of `run`:
  - stdout/stderr streamed to terminal
  - a JSON one-liner appended to ~/arena-bridge/logs/skills.jsonl with
    {ts, skill, args, exit, duration_sec}
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
SK = ROOT / "skills"
LOGS = ROOT / "logs"
LOG_FILE = LOGS / "skills.jsonl"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")




def _fire_hook(event: str, target: str, args=None, exit_code: int = 0) -> None:
    """Запустить хуки события через hooks_runner. Тихо игнорирует если его нет."""
    try:
        import subprocess as _sp, json as _j
        runner = ROOT / "bin" / "hooks_runner.py"
        if not runner.exists():
            runner = ROOT / "scripts" / "hooks_runner.py"
        if not runner.exists():
            return
        _sp.run([sys.executable, str(runner), "run", event,
                 "--target", target or "",
                 "--args", _j.dumps(args or {}),
                 "--exit", str(exit_code)],
                timeout=70, check=False)
    except Exception:
        pass


def find_skill_dir(name: str) -> Path | None:
    """name can be 'core/digest' or just 'digest' (first match wins)."""
    name = name.strip().strip("/")
    if not name:
        return None
    # exact namespaced path first
    cand = SK / name
    if cand.is_dir() and (cand / "SKILL.md").exists():
        return cand
    # fallback: search by basename
    if "/" not in name:
        for p in SK.rglob("SKILL.md"):
            if p.parent.name == name:
                return p.parent
    return None


def list_skills(_args) -> int:
    if not SK.exists():
        print("(no skills installed)")
        return 0
    rows: list[tuple[str, str]] = []
    for skill_md in sorted(SK.rglob("SKILL.md")):
        rel = skill_md.parent.relative_to(SK).as_posix()
        # first non-empty, non-heading line of SKILL.md as one-line description
        desc = ""
        for line in skill_md.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                desc = s[:100]
                break
        rows.append((rel, desc))
    if not rows:
        print("(no skills found)")
        return 0
    width = max(len(r[0]) for r in rows)
    for name, desc in rows:
        print(f"{name.ljust(width)}  {desc}")
    return 0


def show_skill(args) -> int:
    d = find_skill_dir(args.name)
    if not d:
        print(f"skill not found: {args.name}", file=sys.stderr)
        return 2
    md = d / "SKILL.md"
    print(md.read_text(encoding="utf-8"))
    # also list executables
    extras = []
    for fname in ("run.sh", "run.py", "manifest.json"):
        if (d / fname).exists():
            extras.append(fname)
    if extras:
        print(f"\n[files: {', '.join(extras)}]  path: {d}")
    return 0


def path_skill(args) -> int:
    d = find_skill_dir(args.name)
    if not d:
        return 2
    print(d)
    return 0


def run_skill(args) -> int:
    _fire_hook("pre_skill", getattr(args, "name", ""), {"args": getattr(args, "skill_args", [])})
    d = find_skill_dir(args.name)
    if not d:
        print(f"skill not found: {args.name}", file=sys.stderr)
        return 2

    manifest = {}
    mf = d / "manifest.json"
    if mf.exists():
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"warning: manifest.json is invalid: {e}", file=sys.stderr)

    timeout = int(manifest.get("timeout", 300))
    if args.timeout:
        timeout = args.timeout

    run_sh = d / "run.sh"
    run_py = d / "run.py"
    venv_py = ROOT / ".venv" / "bin" / "python"

    if run_sh.exists():
        cmd = ["bash", str(run_sh), *args.skill_args]
    elif run_py.exists():
        py = str(venv_py) if venv_py.exists() else sys.executable
        cmd = [py, str(run_py), *args.skill_args]
    else:
        print(f"skill '{args.name}' has neither run.sh nor run.py", file=sys.stderr)
        return 2

    LOGS.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("ARENA_AGENT_HOME", str(ROOT))
    env["SKILL_NAME"] = d.relative_to(SK).as_posix()
    env["SKILL_DIR"] = str(d)

    start = time.monotonic()
    rc = 0
    try:
        cp = subprocess.run(cmd, cwd=str(d), env=env, timeout=timeout)
        rc = cp.returncode
    except subprocess.TimeoutExpired:
        rc = 124
        print(f"\n[skill timeout after {timeout}s]", file=sys.stderr)
    except KeyboardInterrupt:
        rc = 130
        print("\n[skill interrupted]", file=sys.stderr)

    duration = round(time.monotonic() - start, 3)
    rec = {
        "ts": now_iso(),
        "skill": env["SKILL_NAME"],
        "args": args.skill_args,
        "exit": rc,
        "duration_sec": duration,
    }
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        try:
            LOG_FILE.chmod(0o600)
        except OSError:
            pass
    except OSError:
        pass
    _fire_hook("post_skill", getattr(args, "name", ""), {"args": getattr(args, "skill_args", [])}, rc)
    return rc


SKILL_TEMPLATE_MD = """# {name}

One-line purpose: TODO.

## Inputs
- argv: TODO

## Outputs
- TODO (stdout, files in reports/, memory facts, ...)

## Notes
TODO
"""

RUN_SH_TEMPLATE = """#!/usr/bin/env bash
set -euo pipefail
# Available env: ARENA_AGENT_HOME, SKILL_NAME, SKILL_DIR
echo "skill ${SKILL_NAME} running with args: $*"
"""

MANIFEST_TEMPLATE = {
    "name": "",
    "description": "",
    "args": [],
    "timeout": 300,
    "mode": "safe",
}


def new_skill(args) -> int:
    name = args.name.strip().strip("/")
    if not name or "/" not in name:
        print("usage: skill new <namespace>/<name>  (e.g. core/digest)", file=sys.stderr)
        return 2
    d = SK / name
    if d.exists():
        print(f"already exists: {d}", file=sys.stderr)
        return 1
    d.mkdir(parents=True, exist_ok=False)
    try:
        d.chmod(0o700)
    except OSError:
        pass
    (d / "SKILL.md").write_text(SKILL_TEMPLATE_MD.format(name=name), encoding="utf-8")
    rs = d / "run.sh"
    rs.write_text(RUN_SH_TEMPLATE, encoding="utf-8")
    try:
        rs.chmod(0o700)
    except OSError:
        pass
    mf = dict(MANIFEST_TEMPLATE)
    mf["name"] = name
    (d / "manifest.json").write_text(json.dumps(mf, indent=2) + "\n", encoding="utf-8")
    for p in (d / "SKILL.md", d / "manifest.json"):
        try:
            p.chmod(0o600)
        except OSError:
            pass
    print(f"scaffolded skill: {d}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="agentctl skill")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=list_skills)

    s = sub.add_parser("show")
    s.add_argument("name")
    s.set_defaults(func=show_skill)

    s = sub.add_parser("path")
    s.add_argument("name")
    s.set_defaults(func=path_skill)

    s = sub.add_parser("run")
    s.add_argument("name")
    s.add_argument("--timeout", type=int, default=0)
    s.add_argument("skill_args", nargs=argparse.REMAINDER)
    s.set_defaults(func=run_skill)

    s = sub.add_parser("new")
    s.add_argument("name", help="namespace/name, e.g. core/digest")
    s.set_defaults(func=new_skill)

    args = ap.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
