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
import argparse, datetime as dt, json, os, shlex, subprocess, sys, time, uuid
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
SUB_DIR = ROOT / "subagents"
SUB_DIR.mkdir(parents=True, exist_ok=True)


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def short_id() -> str:
    return uuid.uuid4().hex[:10]


def spawn(args) -> int:
    sid = short_id()
    sd = SUB_DIR / sid
    sd.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": sid, "name": args.name or "anon", "cmd": args.cmd,
        "created": now_utc(), "timeout": args.timeout, "wait": args.wait,
        "status": "running",
    }
    (sd / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    out_path = sd / "stdout.log"
    err_path = sd / "stderr.log"
    summary_path = sd / "summary.json"

    # env: пробрасываем ARENA_*, помечаем subagent
    env = os.environ.copy()
    env.update({
        "ARENA_SUBAGENT_ID": sid,
        "ARENA_SUBAGENT_NAME": meta["name"],
        "ARENA_AGENT_HOME": str(ROOT),
    })

    t0 = time.time()
    if args.wait:
        # синхронно с таймаутом
        with open(out_path, "w") as fout, open(err_path, "w") as ferr:
            try:
                p = subprocess.run(args.cmd, shell=True, env=env, stdout=fout, stderr=ferr,
                                   timeout=args.timeout, cwd=str(ROOT))
                rc = p.returncode
                status = "ok" if rc == 0 else "fail"
            except subprocess.TimeoutExpired:
                rc = -1; status = "timeout"
    else:
        # фоном через nohup; subagent сам пишет в свои файлы
        with open(out_path, "w") as fout, open(err_path, "w") as ferr:
            p = subprocess.Popen(args.cmd, shell=True, env=env,
                                 stdout=fout, stderr=ferr, cwd=str(ROOT),
                                 start_new_session=True)
        rc = None; status = "spawned"
        # сохраним pid для status checks
        (sd / "pid").write_text(str(p.pid))

    dur = round(time.time() - t0, 3)

    # summary
    out_tail = ""
    err_tail = ""
    try:
        out_tail = "\n".join(open(out_path).read().splitlines()[-args.max_out:])
        err_tail = "\n".join(open(err_path).read().splitlines()[-30:])
    except Exception: pass

    summary = {
        "id": sid, "name": meta["name"], "status": status, "exit": rc,
        "duration_sec": dur, "stdout_tail": out_tail, "stderr_tail": err_tail,
        "paths": {"stdout": str(out_path), "stderr": str(err_path), "dir": str(sd)},
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    meta["status"] = status; meta["exit"] = rc; meta["duration_sec"] = dur
    (sd / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if status in ("ok", "spawned") else 1


def list_cmd(_args) -> int:
    items = []
    for sd in sorted(SUB_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        meta_p = sd / "meta.json"
        if not meta_p.exists(): continue
        try:
            m = json.loads(meta_p.read_text())
            items.append({"id": m.get("id"), "name": m.get("name"), "status": m.get("status"),
                          "exit": m.get("exit"), "dur": m.get("duration_sec"), "created": m.get("created")})
        except Exception: pass
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


def show_cmd(args) -> int:
    sd = SUB_DIR / args.id
    s = sd / "summary.json"
    if not s.exists():
        print(f"no such subagent: {args.id}", file=sys.stderr); return 1
    print(s.read_text())
    return 0


def rm_cmd(args) -> int:
    sd = SUB_DIR / args.id
    if not sd.exists():
        print(f"no such subagent: {args.id}", file=sys.stderr); return 1
    import shutil
    shutil.rmtree(sd)
    print(f"removed: {sd}")
    return 0


def prune_cmd(args) -> int:
    items = sorted(SUB_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    to_delete = items[args.keep:]
    import shutil
    for sd in to_delete:
        shutil.rmtree(sd, ignore_errors=True)
    print(f"kept={min(len(items), args.keep)} removed={len(to_delete)}")
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
    sh = sub.add_parser("show"); sh.add_argument("id"); sh.set_defaults(func=show_cmd)
    rm = sub.add_parser("rm");   rm.add_argument("id"); rm.set_defaults(func=rm_cmd)
    pr = sub.add_parser("prune"); pr.add_argument("--keep", type=int, default=10); pr.set_defaults(func=prune_cmd)

    args = ap.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
