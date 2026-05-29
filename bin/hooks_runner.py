#!/usr/bin/env python3
"""hooks_runner.py — простой движок хуков для Arena Agent.

Идея (вдохновлена Claude Code hooks): на любое событие может срабатывать
один или несколько пользовательских скриптов. Хуки лежат как обычные файлы:

  ~/arena-bridge/hooks/<event>.d/01-name.sh
  ~/arena-bridge/hooks/<event>.d/02-other.py

События (event):
  pre_skill         — перед `agentctl skill run`
  post_skill        — после `agentctl skill run`
  pre_mission       — перед `agentctl mission run`
  post_mission      — после `agentctl mission run`
  pre_exec          — может вызываться вручную (мы НЕ модифицируем bridge)
  post_exec         — то же
  startup           — при запуске agent recovery / dashboard refresh
  custom            — что угодно, по имени

Каждый хук получает контекст через env vars:
  ARENA_EVENT, ARENA_TARGET, ARENA_ARGS_JSON, ARENA_EXIT (для post-*)

Использование:
  hooks_runner.py list
  hooks_runner.py run <event> [--target NAME] [--args JSON] [--exit N]
  hooks_runner.py add <event> <name> --cmd 'echo hi $ARENA_TARGET'
  hooks_runner.py rm  <event> <name>
"""
from __future__ import annotations
import argparse, json, os, stat, subprocess, sys, time
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
HOOKS = ROOT / "hooks"
LOGS = ROOT / "logs"
LOG_FILE = LOGS / "hooks.jsonl"

EVENTS = ("pre_skill", "post_skill", "pre_mission", "post_mission",
          "pre_exec", "post_exec", "startup", "custom")


def event_dir(ev: str) -> Path:
    return HOOKS / f"{ev}.d"


def list_hooks() -> int:
    HOOKS.mkdir(parents=True, exist_ok=True)
    found = {}
    for ev in EVENTS:
        d = event_dir(ev)
        if d.exists():
            files = sorted(d.iterdir())
            if files:
                found[ev] = [f.name for f in files]
    print(json.dumps(found, ensure_ascii=False, indent=2))
    return 0


def run_event(event: str, target: str = "", args_json: str = "{}", exit_code: int = 0) -> int:
    d = event_dir(event)
    if not d.exists():
        return 0  # нет хуков — это норма
    env = os.environ.copy()
    env.update({
        "ARENA_EVENT": event,
        "ARENA_TARGET": target,
        "ARENA_ARGS_JSON": args_json,
        "ARENA_EXIT": str(exit_code),
        "ARENA_AGENT_HOME": str(ROOT),
    })
    LOGS.mkdir(parents=True, exist_ok=True)
    failed = 0
    for f in sorted(d.iterdir()):
        if not os.access(f, os.X_OK):
            continue
        t0 = time.time()
        try:
            p = subprocess.run([str(f)], env=env, capture_output=True, text=True, timeout=60)
            rc = p.returncode
        except Exception as e:
            rc = -1
            p = type("X", (), {"stdout": "", "stderr": str(e)})()
        rec = {
            "ts": int(t0), "event": event, "hook": f.name, "target": target,
            "exit": rc, "duration_ms": int((time.time() - t0) * 1000),
            "stdout_head": (getattr(p, "stdout", "") or "")[:500],
            "stderr_head": (getattr(p, "stderr", "") or "")[:500],
        }
        with open(LOG_FILE, "a", encoding="utf-8") as lf:
            lf.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if rc != 0:
            failed += 1
            print(f"[hook FAIL] {event}/{f.name} exit={rc}: {getattr(p,'stderr','')[:200]}", file=sys.stderr)
    return failed


def add_hook(event: str, name: str, cmd: str) -> int:
    d = event_dir(event)
    d.mkdir(parents=True, exist_ok=True)
    # auto-prefix с номером
    existing = sorted([f for f in d.iterdir() if f.name[:2].isdigit()])
    next_n = int(existing[-1].name[:2]) + 1 if existing else 1
    fname = f"{next_n:02d}-{name}.sh"
    path = d / fname
    path.write_text(f"#!/usr/bin/env bash\n# auto-generated hook: {event}/{name}\nset -e\n{cmd}\n")
    path.chmod(0o755)
    print(f"created: {path}")
    return 0


def rm_hook(event: str, name: str) -> int:
    d = event_dir(event)
    if not d.exists():
        print(f"no such event dir: {d}", file=sys.stderr); return 1
    matched = [f for f in d.iterdir() if name in f.name]
    if not matched:
        print(f"no hook matching '{name}' in {event}", file=sys.stderr); return 1
    for f in matched:
        f.unlink()
        print(f"removed: {f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="hooks_runner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("run")
    r.add_argument("event"); r.add_argument("--target", default="")
    r.add_argument("--args", default="{}"); r.add_argument("--exit", type=int, default=0)
    a = sub.add_parser("add")
    a.add_argument("event"); a.add_argument("name"); a.add_argument("--cmd", required=True)
    rm = sub.add_parser("rm"); rm.add_argument("event"); rm.add_argument("name")
    args = ap.parse_args()
    if args.cmd == "list": return list_hooks()
    if args.cmd == "run":  return run_event(args.event, args.target, args.args, getattr(args,"exit",0))
    if args.cmd == "add":  return add_hook(args.event, args.name, args.cmd)
    if args.cmd == "rm":   return rm_hook(args.event, args.name)
    return 2


if __name__ == "__main__":
    sys.exit(main())
