"""Slash command helpers for chat REPL."""
from __future__ import annotations

from arena.chat_cli.common import *  # noqa: F401,F403

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
        cp = subprocess.run(arg, shell=True, capture_output=True, text=True,  # nosec B602 -- chat exec is an interactive CLI command; the shell string is the operator's own input by design.  # nosemgrep: subprocess-shell-true -- legitimate CLI-side helper (see bandit B602 nosec on the same line for the specific rationale)
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
