"""Modular chat REPL implementation."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

os.umask(0o077)
HOME = Path(os.environ.get("ARENA_AGENT_HOME", Path.home() / "arena-bridge"))
SESS_DIR = HOME / "memory" / "sessions"
CURRENT = SESS_DIR / "current"
AGENTCTL = HOME / "bin" / "agentctl"
DESTRUCTIVE = re.compile(
    r"(\brm\s+-rf?\b|\bmkfs\b|\bdd\s+if=|\bshutdown\b|\breboot\b|:\(\)\{|"
    r"\bchmod\s+-R\s+777\b|curl\s+[^|]*\|\s*(sh|bash)\b|wget\s+[^|]*\|\s*(sh|bash)\b|"
    r"\bsudo\s+rm\b)"
)

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:40] or "session"

def open_session(name: str | None) -> Path:
    SESS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    slug = slugify(name) if name else "chat"
    path = SESS_DIR / f"{stamp}-{slug}.jsonl"
    path.touch()
    try:
        path.chmod(0o600)  # ACL-proof: force owner-only
    except OSError:
        pass
    try:
        if CURRENT.is_symlink() or CURRENT.exists():
            CURRENT.unlink()
        CURRENT.symlink_to(path.name)
    except OSError as e:
        print(f"warning: could not update current symlink: {e}", file=sys.stderr)
    return path

def write_event(path: Path, role: str, kind: str, content: str, **meta) -> None:
    rec = {"ts": now_iso(), "role": role, "kind": kind, "content": content}
    if meta:
        rec["meta"] = meta
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    # flock-protected append, so the remote agent can also append concurrently.
    with path.open("a", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(line)
            f.flush()
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass

def run_agentctl(args: list[str], timeout: int = 180) -> tuple[int, str]:
    if not AGENTCTL.exists():
        return 127, f"agentctl not found at {AGENTCTL}"
    try:
        cp = subprocess.run(
            [str(AGENTCTL), *args],
            capture_output=True, text=True, timeout=timeout,
        )
        out = (cp.stdout or "")
        if cp.stderr:
            out += ("\n" if out else "") + cp.stderr
        return cp.returncode, out.rstrip()
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"

def confirm(prompt: str) -> bool:
    try:
        ans = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return ans in {"y", "yes"}
