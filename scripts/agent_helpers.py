#!/usr/bin/env python3
"""
agent_helpers.py — utilities for the remote agent (Arena chat side).

These are *meta* helpers: they live on the CachyOS machine but exist to make
my (the remote agent's) life easier when deploying patches via the bridge.

Provides:
  - safe_write(path, content, mode=0o600) — atomic write + chmod (ACL-proof)
  - backup_file(path) -> backup_path — timestamped .bak alongside the file
  - verify_python(path) — import-check, returns (ok, message)
  - verify_bash(path) — `bash -n`, returns (ok, message)
  - patch_block(path, anchor, new_block, marker, position='before')
        — idempotent insertion using a marker string for re-run safety
  - patch_replace(path, old, new, marker=None)
  - run_local(cmd, timeout=60) -> (rc, out)
  - load_facts(query='', limit=50) — read memory facts JSONL
  - put_fact(key, value, tags=None) — append a fact (correct tags handling)

CLI:
  agent_helpers.py self-check          — run a battery of internal tests
  agent_helpers.py facts [query]       — list facts (proper tag rendering)
  agent_helpers.py put <key> <tag,tag> <value...>
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME",
                           str(Path.home() / "arena-bridge"))).expanduser()
FACTS = ROOT / "memory" / "facts.jsonl"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def safe_write(path: Path | str, content: str, mode: int = 0o600) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    try:
        tmp.chmod(mode)
    except OSError:
        pass
    tmp.replace(p)
    try:
        p.chmod(mode)  # ACL-proof: explicit chmod after replace
    except OSError:
        pass
    return p


def backup_file(path: Path | str) -> Path | None:
    p = Path(path)
    if not p.exists():
        return None
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = p.with_suffix(p.suffix + f".bak-{stamp}")
    shutil.copy2(p, bak)
    try:
        bak.chmod(0o600)
    except OSError:
        pass
    return bak


def verify_python(path: Path | str) -> tuple[bool, str]:
    p = Path(path)
    if not p.exists():
        return False, f"missing: {p}"
    try:
        spec = importlib.util.spec_from_file_location("_check", str(p))
        if spec is None or spec.loader is None:
            return False, "no spec/loader"
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return True, "ok"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def verify_bash(path: Path | str) -> tuple[bool, str]:
    p = Path(path)
    if not p.exists():
        return False, f"missing: {p}"
    cp = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
    if cp.returncode == 0:
        return True, "ok"
    return False, (cp.stderr or cp.stdout or "non-zero exit").strip()


def patch_block(path: Path | str, anchor: str, new_block: str,
                marker: str, position: str = "before") -> str:
    """
    Insert `new_block` near `anchor` in file at `path`. Idempotent: if `marker`
    already present in file, no-op.

    position: 'before' (insert immediately before anchor)
              'after'  (insert immediately after anchor)
              'replace' (replace `anchor` with `new_block` — anchor must occur
                         exactly once)
    Returns status string.
    """
    p = Path(path)
    src = p.read_text(encoding="utf-8")
    if marker and marker in src:
        return f"already patched (marker: {marker!r})"
    if anchor not in src:
        raise ValueError(f"anchor not found in {p}: {anchor!r}")
    if position == "before":
        new_src = src.replace(anchor, new_block + anchor, 1)
    elif position == "after":
        new_src = src.replace(anchor, anchor + new_block, 1)
    elif position == "replace":
        new_src = src.replace(anchor, new_block, 1)
    else:
        raise ValueError(f"unknown position: {position}")
    backup_file(p)
    safe_write(p, new_src, mode=p.stat().st_mode & 0o777)
    return "patched"


def patch_replace(path: Path | str, old: str, new: str,
                  marker: str | None = None) -> str:
    p = Path(path)
    src = p.read_text(encoding="utf-8")
    if marker and marker in src:
        return f"already patched (marker: {marker!r})"
    if old not in src:
        raise ValueError(f"old text not found in {p}")
    backup_file(p)
    safe_write(p, src.replace(old, new, 1), mode=p.stat().st_mode & 0o777)
    return "patched"


def run_local(cmd: str | list[str], timeout: int = 60,
              cwd: Path | str | None = None) -> tuple[int, str]:
    if isinstance(cmd, str):
        cp = subprocess.run(cmd, shell=True, capture_output=True,
                            text=True, timeout=timeout,
                            cwd=str(cwd) if cwd else None)
    else:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=timeout,
                            cwd=str(cwd) if cwd else None)
    out = (cp.stdout or "")
    if cp.stderr:
        out += ("\n" if out else "") + cp.stderr
    return cp.returncode, out.rstrip()


def load_facts(query: str = "", limit: int = 50) -> list[dict]:
    if not FACTS.exists():
        return []
    q = query.lower()
    out = []
    for ln in FACTS.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if q:
            hay = (str(obj.get("key", "")) + " "
                   + str(obj.get("value", "")) + " "
                   + " ".join(obj.get("tags", []) or [])).lower()
            if q not in hay:
                continue
        out.append(obj)
    return out[-limit:]


def put_fact(key: str, value: str, tags: list[str] | None = None) -> None:
    FACTS.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": now_iso(), "type": "fact",
           "key": key, "value": value,
           "tags": tags or []}
    with FACTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        FACTS.chmod(0o600)
    except OSError:
        pass


# ----- CLI -----

def cli_self_check(_args) -> int:
    issues = []
    # 1. ROOT exists
    if not ROOT.is_dir():
        issues.append(f"ROOT missing: {ROOT}")
    # 2. agentctl is executable
    a = ROOT / "bin" / "agentctl"
    if not a.is_file() or not os.access(a, os.X_OK):
        issues.append(f"agentctl not executable: {a}")
    else:
        ok, msg = verify_bash(a)
        if not ok:
            issues.append(f"agentctl bash -n failed: {msg}")
    # 3. venv python works
    venv_py = ROOT / ".venv" / "bin" / "python"
    if not venv_py.is_file():
        issues.append(f"venv python missing: {venv_py}")
    # 4. critical python scripts import
    for name in ("memory.py", "task_runner.py", "chat.py",
                 "chat_append.py", "skill_runner.py", "recovery_prompt.py",
                 "agent_helpers.py"):
        path = ROOT / "scripts" / name
        if not path.exists():
            issues.append(f"missing script: {name}")
            continue
        ok, msg = verify_python(path)
        if not ok:
            issues.append(f"{name}: {msg}")
    # 5. services
    cp = subprocess.run(["systemctl", "--user", "is-active",
                         "arena-local-bridge.service",
                         "arena-task-runner.service"],
                        capture_output=True, text=True)
    states = cp.stdout.strip().splitlines()
    if len(states) >= 1 and states[0] != "active":
        issues.append(f"arena-local-bridge.service: {states[0]}")
    if len(states) >= 2 and states[1] != "active":
        issues.append(f"arena-task-runner.service: {states[1]}")
    # 6. session dir
    sd = ROOT / "memory" / "sessions"
    if not sd.is_dir():
        issues.append(f"sessions dir missing: {sd}")
    # report
    if not issues:
        print("OK — all self-checks passed")
        return 0
    print(f"FAIL — {len(issues)} issue(s):")
    for i in issues:
        print(f"  - {i}")
    return 1


def cli_facts(args) -> int:
    rows = load_facts(args.query or "", args.limit)
    if not rows:
        print("(no facts)")
        return 0
    for obj in rows:
        tags = ",".join(obj.get("tags", []) or []) or "-"
        print(f"[{obj.get('ts')}] {obj.get('key')} [{tags}] {obj.get('value')}")
    return 0


def cli_put(args) -> int:
    tags = [t for t in args.tags.split(",") if t] if args.tags else []
    put_fact(args.key, " ".join(args.value), tags=tags)
    print("ok")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="agent_helpers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("self-check").set_defaults(func=cli_self_check)
    s = sub.add_parser("facts")
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cli_facts)
    s = sub.add_parser("put")
    s.add_argument("key")
    s.add_argument("tags", help="comma-separated tags, or '-' for none")
    s.add_argument("value", nargs=argparse.REMAINDER)
    s.set_defaults(func=cli_put)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
