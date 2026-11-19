#!/usr/bin/env python3
"""subagent.py — изолированный sub-agent для делегирования задач.

Идея (от Gemini CLI / Claude Code): запустить «вторую инстанцию агента» на отдельную
задачу, чтобы не загромождать контекст основного LLM. Возвращается только summary
(stdout последних N строк + exit + duration + ссылки на отчёты).

Реализация: оборачиваем команду в task_runner для асинхрона + дополнительно
поддерживаем синхронный запуск (--wait). Sub-agent имеет свой workspace:
~/arena-bridge/subagents/<id>/ с stdout, stderr, summary.json.

Команды:
  spawn  "<cmd>" [--name NAME] [--timeout SEC] [--wait] [--max-out N]
  list                                  — последние 20 sub-agents
  show   <id>                           — JSON summary + stdout/stderr хвост
  rm     <id>                           — удалить директорию sub-agent
  prune  [--keep N]                     — оставить последние N
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

from arena.home import agent_home, code_root
from arena.private_state import private_directory, write_private_json

ROOT = agent_home()
SUB_DIR = ROOT / "subagents"
private_directory(ROOT)
private_directory(SUB_DIR)
META_FILE = "meta.json"


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def short_id() -> str:
    return uuid.uuid4().hex[:10]


def _subagent_env(sid: str, name: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update({"ARENA_SUBAGENT_ID": sid, "ARENA_SUBAGENT_NAME": name, "ARENA_AGENT_HOME": str(ROOT)})
    return env


def _output_tail(path: Path, lines: int) -> str:
    if lines <= 0:
        return ""
    try:
        return "\n".join(path.read_text().splitlines()[-lines:])
    except (OSError, UnicodeError) as exc:
        print(f"[subagent] Cannot read output tail {path}: {exc}", file=sys.stderr)
        return ""


def _run_waiting(sd: Path, env: dict[str, str]) -> dict:
    from arena.subagent_lifecycle import run

    # Apply the same identity environment as a detached monitor.
    previous = {key: os.environ.get(key) for key in ("ARENA_SUBAGENT_ID", "ARENA_SUBAGENT_NAME", "ARENA_AGENT_HOME")}
    try:
        os.environ.update({key: env[key] for key in previous})
        return run(sd)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def spawn(args) -> int:
    if args.timeout <= 0 or args.max_out <= 0:
        print("timeout and max-out must be positive", file=sys.stderr)
        return 1
    sid = short_id()
    sd = (SUB_DIR / sid).resolve()
    meta = {"id": sid, "name": args.name or "anon", "cmd": args.cmd,
            "created": now_utc(), "timeout": args.timeout, "wait": args.wait,
            "status": "running" if args.wait else "spawned", "cwd": str(ROOT.resolve()),
            "max_out": args.max_out}
    write_private_json(sd / META_FILE, meta)
    env = _subagent_env(sid, meta["name"])
    if args.wait:
        summary = _run_waiting(sd, env)
    else:
        summary = {"id": sid, "name": meta["name"], "status": "spawned", "exit": None,
                   "paths": {"stdout": str(sd / "stdout.log"), "stderr": str(sd / "stderr.log"),
                             "dir": str(sd)}}
        write_private_json(sd / "summary.json", summary)
        try:
            process = subprocess.Popen([sys.executable, "-m", "arena.subagent_lifecycle", str(sd)],  # nosec B603 -- fixed interpreter and literal package module; generated private run directory is only data
                                       env=env, cwd=str(code_root()), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       start_new_session=True)
        except OSError as exc:
            summary.update(status="fail", error=str(exc))
            meta.update(status="fail", error=str(exc))
            write_private_json(sd / "summary.json", summary)
            write_private_json(sd / META_FILE, meta)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 1
        write_private_json(sd / "pid", process.pid)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] in ("ok", "spawned") else 1


def list_cmd(_args) -> int:
    items = []
    for sd in sorted(SUB_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        meta_p = sd / META_FILE
        if not meta_p.exists():
            continue
        try:
            m = json.loads(meta_p.read_text())
            items.append({"id": m.get("id"), "name": m.get("name"), "status": m.get("status"),
                          "exit": m.get("exit"), "dur": m.get("duration_sec"), "created": m.get("created")})
        except (OSError, ValueError, AttributeError) as exc:
            print(f"[subagent] Cannot read metadata {meta_p}: {exc}", file=sys.stderr)
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


def show_cmd(args) -> int:
    sd = SUB_DIR / args.id
    s = sd / "summary.json"
    if not s.exists():
        print(f"no such subagent: {args.id}", file=sys.stderr)
        return 1
    print(s.read_text())
    return 0


def _contained_run(run_id: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{10}", run_id):
        return None
    candidate = SUB_DIR / run_id
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(SUB_DIR.resolve()):
        return None
    return candidate


def _active_run(directory: Path) -> bool:
    try:
        meta = json.loads((directory / META_FILE).read_text())
        return meta.get("status") in {"running", "spawned"}
    except (OSError, ValueError, AttributeError):
        return True  # Unknown state is not permission to delete a live workspace.


def rm_cmd(args) -> int:
    sd = _contained_run(args.id)
    if sd is None:
        print("invalid subagent id", file=sys.stderr)
        return 1
    if _active_run(sd):
        print("refusing to remove an active or unreadable subagent", file=sys.stderr)
        return 1
    if not sd.exists():
        print(f"no such subagent: {args.id}", file=sys.stderr)
        return 1
    import shutil
    shutil.rmtree(sd)
    print(f"removed: {sd}")
    return 0


def prune_cmd(args) -> int:
    import shutil

    if args.keep < 0:
        print("keep must be nonnegative", file=sys.stderr)
        return 1
    items = sorted(SUB_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for sd in items[args.keep:]:
        if _contained_run(sd.name) is not None and not _active_run(sd):
            shutil.rmtree(sd)
            removed += 1
    print(f"kept={len(items) - removed} removed={removed}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="subagent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("spawn")
    sp.add_argument("cmd")
    sp.add_argument("--name", default="")
    sp.add_argument("--timeout", type=int, default=300)
    sp.add_argument("--wait", action="store_true")
    sp.add_argument("--max-out", type=int, default=40)
    sp.set_defaults(func=spawn)

    sub.add_parser("list").set_defaults(func=list_cmd)
    sh = sub.add_parser("show")
    sh.add_argument("id")
    sh.set_defaults(func=show_cmd)
    rm = sub.add_parser("rm")
    rm.add_argument("id")
    rm.set_defaults(func=rm_cmd)
    pr = sub.add_parser("prune")
    pr.add_argument("--keep", type=int, default=10)
    pr.set_defaults(func=prune_cmd)

    args = ap.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
