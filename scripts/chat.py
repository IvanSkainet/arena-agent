#!/usr/bin/env python3
"""
agentctl chat — local REPL for Arena Agent.

The LLM brain lives in the Arena.ai web chat. This REPL is the keyboard/eyes
for the local platform. Every line is journaled to a JSONL session file so the
remote agent (the assistant in the Arena chat) can read it via the bridge and
append replies to the same file.

Session file: ~/arena-bridge/memory/sessions/<stamp>-<slug>.jsonl
Current ptr:  ~/arena-bridge/memory/sessions/current  (symlink)

Slash commands (v0.1):
  /help                          show this help
  /exit  /quit                   leave the REPL
  /mode safe|edit|full           switch permission level (default: safe)
  /project [name]                show or switch current project (uses project_git)
  /web <url>                     smart fetch: http -> browser-report fallback
  /recon <target>                smart recon: ip / headers / recon-domain
  /run <shell command>           run shell, gated by /mode
  /task <cmd>                    submit background task to queue
  /remember <text>               memory-remember chat <text>  (tag: chat)
  /recall [query]                memory-recall [query]
  /skill [name]                  skill-list or skill-show <name>
  /context                       compact digest to paste into a new Arena chat
  /tail [n]                      show last n events of current session (default 20)
  /status                        agentctl status (head)
  /agent-tail [n]                show last n messages from the remote agent (default 5)
  /wait-agent [s]                block up to s seconds for a new agent message (default 120)

Anything not starting with "/" is logged as a user message — the remote agent
sees it via `tail` on the session file.
"""
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
from pathlib import Path

os.umask(0o077)  # session files must be owner-only

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


# ---------- slash command handlers ----------

def cmd_web(arg: str) -> tuple[int, str]:
    arg = arg.strip()
    if not arg:
        return 2, "usage: /web <url>"
    code, out = run_agentctl(["http", arg])
    if code == 0 and out:
        return code, out
    # fallback to browser-based fetch
    return run_agentctl(["browser-report", arg])


def cmd_recon(arg: str) -> tuple[int, str]:
    arg = arg.strip()
    if not arg:
        return 2, "usage: /recon <ip|url|domain>"
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", arg):
        return run_agentctl(["ip"])  # ip script ignores arg; reports local IP info
    if arg.startswith(("http://", "https://")):
        return run_agentctl(["headers", arg])
    return run_agentctl(["recon-domain", arg])


def current_project() -> str | None:
    code, out = run_agentctl(["project-current"], timeout=10)
    if code == 0 and out.strip() and "no current" not in out.lower():
        return out.strip().splitlines()[0]
    return None


def cmd_run(arg: str, mode: str) -> tuple[int, str]:
    if not arg.strip():
        return 2, "usage: /run <shell command>"
    if DESTRUCTIVE.search(arg):
        if not confirm(f"DESTRUCTIVE command detected. Proceed?\n  {arg}"):
            return 1, "aborted by user"
    if mode == "safe":
        if not confirm(f"[safe mode] allow this command?\n  {arg}"):
            return 1, "aborted (safe mode)"
    cwd = None
    if mode == "edit":
        proj = current_project()
        if proj:
            cand = HOME / "projects" / proj
            if cand.is_dir():
                cwd = cand
    try:
        cp = subprocess.run(arg, shell=True, capture_output=True, text=True,
                            timeout=600, cwd=cwd)
        out = (cp.stdout or "")
        if cp.stderr:
            out += ("\n" if out else "") + cp.stderr
        return cp.returncode, out.rstrip()
    except subprocess.TimeoutExpired:
        return 124, "command timed out after 600s"


def cmd_context() -> str:
    lines = [f"# Arena Agent — quick context  ({now_iso()})", ""]
    code, status = run_agentctl(["status"], timeout=30)
    lines += ["## status (head)", "```text",
              "\n".join(status.splitlines()[:30]), "```", ""]
    code, mem = run_agentctl(["memory-recall"], timeout=15)
    if mem:
        lines += ["## recent memory (top)", "```text",
                  "\n".join(mem.splitlines()[:20]), "```", ""]
    proj = current_project()
    if proj:
        lines += [f"## current project: `{proj}`", ""]
    code, last = run_agentctl(["task-last"], timeout=10)
    if last:
        lines += ["## last task", "```text",
                  "\n".join(last.splitlines()[:15]), "```", ""]
    return "\n".join(lines)


def print_help() -> None:
    print(__doc__)


# ---------- REPL ----------

def repl(session_path: Path, mode: str) -> int:
    proj = current_project() or "-"
    print(f"arena-bridge chat — session: {session_path.name}")
    print(f"mode: {mode}   project: {proj}")
    print("type /help for commands, /exit to quit")

    while True:
        proj = current_project() or "-"
        try:
            line = input(f"[{mode}|{proj}] > ")
        except (EOFError, KeyboardInterrupt):
            print()
            write_event(session_path, "system", "note", "session ended")
            return 0
        line = line.rstrip()
        if not line:
            continue

        if not line.startswith("/"):
            write_event(session_path, "user", "message", line)
            print("(logged — remote agent will see it via bridge)")
            continue

        parts = line.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        write_event(session_path, "user", "slash", line)

        out, code = "", 0
        if cmd in ("/exit", "/quit"):
            write_event(session_path, "system", "note", "session ended")
            return 0
        elif cmd == "/help":
            print_help()
            continue
        elif cmd == "/mode":
            if arg.strip() in ("safe", "edit", "full"):
                mode = arg.strip()
                write_event(session_path, "system", "note", f"mode={mode}")
                out = f"mode set to {mode}"
            else:
                out, code = "usage: /mode safe|edit|full", 2
        elif cmd == "/project":
            if arg.strip():
                code, out = run_agentctl(["project-use", arg.strip()])
            else:
                code, out = run_agentctl(["project-current"])
        elif cmd == "/web":
            code, out = cmd_web(arg)
        elif cmd == "/recon":
            code, out = cmd_recon(arg)
        elif cmd == "/run":
            code, out = cmd_run(arg, mode)
        elif cmd == "/task":
            if arg.strip():
                code, out = run_agentctl(["task-submit", arg])
            else:
                code, out = run_agentctl(["tasks"])
        elif cmd == "/remember":
            if arg.strip():
                code, out = run_agentctl(["memory-remember", "chat", arg,
                                          "--tags", "chat", "repl"])
            else:
                out, code = "usage: /remember <text>", 2
        elif cmd == "/recall":
            code, out = run_agentctl(["memory-recall", arg] if arg.strip()
                                     else ["memory-recall"])
        elif cmd == "/skill":
            if arg.strip():
                code, out = run_agentctl(["skill-show", *shlex.split(arg)])
            else:
                code, out = run_agentctl(["skill-list"])
        elif cmd == "/context":
            out = cmd_context()
        elif cmd == "/tail":
            try:
                n = int(arg.strip()) if arg.strip() else 20
            except ValueError:
                n = 20
            lines_all = session_path.read_text(encoding="utf-8").splitlines()
            out = "\n".join(lines_all[-n:])
        elif cmd == "/status":
            code, out = run_agentctl(["status"])
            out = "\n".join(out.splitlines()[:40])
        elif cmd == "/agent-tail":
            try:
                n = int(arg.strip()) if arg.strip() else 5
            except ValueError:
                n = 5
            import json as _json
            msgs = []
            for ln in session_path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = _json.loads(ln)
                except Exception:
                    continue
                if rec.get("role") == "agent":
                    msgs.append(rec)
            tail = msgs[-n:]
            if not tail:
                out = "(no agent messages yet)"
            else:
                out = (chr(10)+chr(10)).join(f"[{m.get('ts','?')}] {m.get('content','')}" for m in tail)
        elif cmd == "/wait-agent":
            try:
                secs = int(arg.strip()) if arg.strip() else 120
            except ValueError:
                secs = 120
            import json as _json, time as _time
            start_size = session_path.stat().st_size
            deadline = _time.monotonic() + secs
            found = None
            print(f"(waiting up to {secs}s for an agent message... Ctrl-C to cancel)")
            try:
                while _time.monotonic() < deadline:
                    cur = session_path.stat().st_size
                    if cur > start_size:
                        # scan new tail
                        with session_path.open("r", encoding="utf-8") as f:
                            f.seek(start_size)
                            for ln in f:
                                try:
                                    rec = _json.loads(ln)
                                except Exception:
                                    continue
                                if rec.get("role") == "agent":
                                    found = rec
                                    break
                        start_size = cur
                        if found:
                            break
                    _time.sleep(1.0)
            except KeyboardInterrupt:
                out, code = "(wait cancelled)", 130
                write_event(session_path, "tool", "result", out, exit=code, slash=cmd)
                print(out)
                continue
            if found:
                out = f"[{found.get('ts','?')}] {found.get('content','')}"
            else:
                out, code = "(timeout — no agent reply)", 124
        else:
            out, code = f"unknown command: {cmd} (try /help)", 2

        write_event(session_path, "tool", "result", out, exit=code, slash=cmd)
        print(out if out else f"(exit {code})")


def main() -> int:
    ap = argparse.ArgumentParser(prog="agentctl chat",
                                 description="Local REPL for Arena Agent")
    ap.add_argument("--name", help="session slug (for the file name)")
    ap.add_argument("--mode", choices=["safe", "edit", "full"], default="safe")
    args = ap.parse_args()
    path = open_session(args.name)
    write_event(path, "system", "note", f"session start mode={args.mode}")
    print(f"session file: {path}")
    try:
        return repl(path, args.mode)
    finally:
        write_event(path, "system", "note", "session closed")


if __name__ == "__main__":
    sys.exit(main())
