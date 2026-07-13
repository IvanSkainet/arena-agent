#!/usr/bin/env python3
"""Cross-platform wrapper around the browser-act CLI.

Replaces the previous bash-only run.sh so the skill works out of the box
on Windows, macOS and Linux. Usage matches the original:

    python run.py doctor
    python run.py extract <url> [browser-act args...]
    python run.py shot <url>
    python run.py open <url>
    python run.py state
    python run.py click <index>
    python run.py type <text>
    python run.py input <index> <text>
    python run.py eval <js>
    python run.py close
    python run.py auth {set <KEY>|clear|status}
    python run.py browsers
    python run.py raw <args...>
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


HOME = Path.home()
DEFAULT_REPORTS = Path(os.environ.get("ARENA_AGENT_HOME") or (HOME / "arena-bridge")) / "reports"
SESSION = os.environ.get("BACT_SESSION", "arena")
UPSTREAM_PACKAGE = "browser-act-cli"


def _find_cli() -> str:
    """Locate browser-act; explore uv/pipx paths as well as PATH."""
    names = ["browser-act"]
    if platform.system().lower() == "windows":
        names = ["browser-act.exe", "browser-act.bat", "browser-act.cmd", "browser-act"]
    for name in names:
        found = shutil.which(name)
        if found:
            return found

    # Fallbacks for common non-PATH tool installs.
    candidates = [
        HOME / ".local" / "bin" / "browser-act",
        HOME / ".local" / "share" / "uv" / "tools" / "browser-act-cli" / "bin" / "browser-act",
    ]
    if platform.system().lower() == "windows":
        candidates += [
            HOME / "AppData" / "Roaming" / "uv" / "tools" / "browser-act-cli" / "Scripts" / "browser-act.exe",
            HOME / "AppData" / "Local" / "pipx" / "venvs" / "browser-act-cli" / "Scripts" / "browser-act.exe",
        ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    sys.stderr.write(
        f"browser-act not found.\n"
        f"Install with: uv tool install {UPSTREAM_PACKAGE} --python 3.12\n"
        f"See https://www.browseract.com/ for docs.\n"
    )
    sys.exit(1)


def _run(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    cli = _find_cli()
    return subprocess.run(
        [cli, *args],
        text=True,
        capture_output=capture,
    )


def _slug(url: str) -> str:
    slug = re.sub(r"^https?://", "", url)
    slug = re.sub(r"[^A-Za-z0-9._\-]+", "_", slug)
    return slug[:60]


def _stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _ensure_reports() -> Path:
    DEFAULT_REPORTS.mkdir(parents=True, exist_ok=True)
    return DEFAULT_REPORTS


HELP = """\
Usage: python run.py <sub> [args]
  doctor                    check install + handshake
  extract <url> [args...]   stealth-extract URL as markdown
  shot <url>                stealth screenshot (PNG)
  open <url>                navigate (session: {session})
  state                     page state
  click <index>             click element by index
  type <text>               type text
  input <index> <text>      click + type
  eval <js>                 run JS, return result
  close                     close session
  auth {{set <KEY>|clear|status}}   manage browser-act API key
  browsers                  list configured browsers
  raw <args...>             pass-through to browser-act
""".format(session=SESSION)


def cmd_help() -> int:
    sys.stdout.write(HELP)
    return 0


def cmd_doctor() -> int:
    cli = _find_cli()
    ver = subprocess.run([cli, "--version"], capture_output=True, text=True)
    sys.stdout.write((ver.stdout or ver.stderr or "").strip() + "\n")
    hs = subprocess.run(
        [cli, "get-skills", "core", "--skill-version", "2.0.0"],
        capture_output=True, text=True,
    )
    if hs.returncode == 0:
        sys.stdout.write("handshake: ok\n")
    else:
        sys.stderr.write(f"handshake: failed ({hs.returncode})\n")
        return hs.returncode or 1
    subprocess.run([cli, "--format", "json", "browser", "list"])
    return 0


def cmd_extract(args: list[str]) -> int:
    if not args:
        sys.stderr.write("usage: extract <url> [browser-act args...]\n"); return 2
    url, *rest = args
    reports = _ensure_reports()
    out = reports / f"bact-extract-{_slug(url)}-{_stamp()}.md"
    proc = subprocess.run(
        [_find_cli(), "--format", "json", "stealth-extract", url,
         "--output", str(out), *rest],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode
    size = out.stat().st_size if out.exists() else 0
    sys.stdout.write(f"saved: {out} ({size} bytes)\n")
    if out.exists():
        text = out.read_text(encoding="utf-8", errors="replace")
        sys.stdout.write(text[:2000])
        if len(text) > 2000:
            sys.stdout.write(f"\n...(truncated, full file at {out})\n")
    return 0


def cmd_shot(args: list[str]) -> int:
    if not args:
        sys.stderr.write("usage: shot <url>\n"); return 2
    url = args[0]
    reports = _ensure_reports()
    out = reports / f"bact-shot-{_slug(url)}-{_stamp()}.png"
    cli = _find_cli()
    subprocess.run([cli, "--format", "json", "--session", SESSION, "navigate", url])
    proc = subprocess.run(
        [cli, "--format", "json", "--session", SESSION, "screenshot", str(out), "--full"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode
    sys.stdout.write(f"saved: {out}\n")
    return 0


def cmd_open(args: list[str]) -> int:
    if not args:
        sys.stderr.write("usage: open <url>\n"); return 2
    _run("--format", "json", "--session", SESSION, "navigate", args[0])
    return 0


def cmd_state(_args: list[str]) -> int:
    _run("--format", "json", "--session", SESSION, "state")
    return 0


def cmd_click(args: list[str]) -> int:
    if not args:
        sys.stderr.write("usage: click <index>\n"); return 2
    _run("--format", "json", "--session", SESSION, "click", args[0])
    return 0


def cmd_type(args: list[str]) -> int:
    if not args:
        sys.stderr.write("usage: type <text>\n"); return 2
    _run("--format", "json", "--session", SESSION, "type", args[0])
    return 0


def cmd_input(args: list[str]) -> int:
    if len(args) < 2:
        sys.stderr.write("usage: input <index> <text>\n"); return 2
    _run("--format", "json", "--session", SESSION, "input", args[0], " ".join(args[1:]))
    return 0


def cmd_eval(args: list[str]) -> int:
    if not args:
        sys.stderr.write("usage: eval <js>\n"); return 2
    _run("--format", "json", "--session", SESSION, "eval", args[0])
    return 0


def cmd_close(_args: list[str]) -> int:
    _run("--format", "json", "--session", SESSION, "session", "close", SESSION)
    return 0


def cmd_auth(args: list[str]) -> int:
    sub = args[0] if args else "status"
    rest = args[1:]
    if sub == "set":
        if not rest:
            sys.stderr.write("usage: auth set <KEY>\n"); return 2
        _run("auth", "set", rest[0])
        return 0
    if sub == "clear":
        _run("auth", "clear")
        return 0
    if sub == "status":
        cfg = HOME / ".local" / "share" / "browseract" / "config.json"
        if platform.system().lower() == "windows":
            cfg = HOME / "AppData" / "Roaming" / "browseract" / "config.json"
        try:
            data = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
            sys.stdout.write("api_key: set\n" if data.get("api_key") else "api_key: not set\n")
        except Exception:
            sys.stdout.write("api_key: not set\n")
        return 0
    sys.stderr.write("usage: auth {set <KEY>|clear|status}\n")
    return 2


def cmd_browsers(_args: list[str]) -> int:
    _run("--format", "json", "browser", "list")
    return 0


def cmd_raw(args: list[str]) -> int:
    proc = subprocess.run([_find_cli(), *args])
    return proc.returncode


COMMANDS = {
    "help": lambda _: cmd_help(), "-h": lambda _: cmd_help(), "--help": lambda _: cmd_help(),
    "doctor": lambda _: cmd_doctor(),
    "extract": cmd_extract,
    "shot": cmd_shot,
    "open": cmd_open,
    "state": cmd_state,
    "click": cmd_click,
    "type": cmd_type,
    "input": cmd_input,
    "eval": cmd_eval,
    "close": cmd_close,
    "auth": cmd_auth,
    "browsers": cmd_browsers,
    "raw": cmd_raw,
}


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        return cmd_help()
    cmd, *rest = argv
    handler = COMMANDS.get(cmd)
    if not handler:
        sys.stderr.write(f"unknown subcommand: {cmd} (try 'python run.py help')\n")
        return 2
    return handler(rest)


if __name__ == "__main__":
    raise SystemExit(main())
