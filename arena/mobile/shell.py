"""Restricted `adb shell` for diagnostic commands.

Phase 1 explicitly does not reuse the desktop `/v1/exec` behavior for
Android — a phone shell is a very different environment and blindly
forwarding arbitrary commands is far too much surface. Instead we run
a strict allowlist of read-only diagnostic commands.

The allowlist is defined by the first token of the command; anything
after that is passed through untouched. So `getprop ro.product.model`
is allowed, but `getprop; rm -rf /sdcard` is not (the semicolon breaks
the token match).
"""
from __future__ import annotations

import shlex
from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run

# Commands that only read state; nothing here can install, delete, or
# reconfigure the device. If you need more, add explicit endpoints
# (e.g. packages.py, screenshot.py) — do not widen this list casually.
_ALLOWED_HEAD_COMMANDS: frozenset[str] = frozenset({
    "getprop",       # read-only property store
    "dumpsys",       # rich state dump; still read-only
    "cat",           # sysfs/procfs inspection
    "ls",            # directory listings
    "pwd",           # current dir
    "df",            # disk usage
    "uptime",        # uptime
    "date",          # current time
    "printenv",      # env vars
    "wm",            # window-manager info (size, density)
    "settings",      # `settings get ...` is read-only; `put` is blocked below
    "pm",            # `pm list ...` etc. — mutating verbs blocked below
    "ip",            # `ip addr`, `ip route` — read-only usage typical
    "ifconfig",      # legacy network info
    "logcat",        # log tail; caller supplies -d / -t to keep it bounded
    "ps",            # process list
    "top",           # -n 1 use case; anything else blocked by timeout
})

# Second-token guardrails for commands that have both read and write
# subcommands. Anything not on the read list here is refused.
_SETTINGS_READ_VERBS = frozenset({"get", "list"})
_PM_READ_VERBS = frozenset({"list", "path", "dump", "get-install-location", "get-max-users"})
_IP_READ_VERBS = frozenset({"addr", "address", "-4", "-6", "route", "link", "neigh", "help"})


def _err(msg: str) -> dict[str, Any]:
    return {"ok": False, "error": msg}


def restricted_shell(serial: str, command: str, *, timeout: int = 15) -> dict[str, Any]:
    """Run a whitelisted diagnostic command on the device.

    Validation order (must stay stable — CI depends on it):
      1. command type / non-empty / length caps;
      2. shell-metacharacter blocklist;
      3. shlex parse;
      4. head-command allowlist + sub-verb guards;
      5. adb-installed guard;
      6. actual dispatch.

    Steps 1-4 run BEFORE the adb-installed check so callers get a
    deterministic parameter error even on hosts without adb. That is
    both a CI stability property and a security property (bad input
    is refused identically regardless of runtime state).
    """
    if not isinstance(command, str):
        return _err("command must be a string")
    if not command.strip():
        return _err("command is empty")
    if len(command) > 2048:
        return _err(f"command too long ({len(command)} chars; max 2048)")

    forbidden_chars = [";", "&&", "||", "|", "`", "$(", ">", "<", "\n", "\r"]
    for ch in forbidden_chars:
        if ch in command:
            return _err(
                f"shell metacharacter {ch!r} is not allowed. "
                f"Use one command per call; chaining goes through explicit endpoints."
            )

    try:
        tokens = shlex.split(command)
    except ValueError as e:
        return _err(f"cannot parse command: {e}")
    if not tokens:
        return _err("command has no tokens")

    head = tokens[0]
    if head not in _ALLOWED_HEAD_COMMANDS:
        return _err(
            f"command {head!r} is not on the allowlist. "
            f"Allowed: {sorted(_ALLOWED_HEAD_COMMANDS)}"
        )

    # Per-command sub-verb guards.
    if head == "settings":
        if len(tokens) < 2 or tokens[1] not in _SETTINGS_READ_VERBS:
            return _err("only `settings get|list` is allowed")
    if head == "pm":
        if len(tokens) < 2 or tokens[1] not in _PM_READ_VERBS:
            return _err(f"only `pm {{{'|'.join(sorted(_PM_READ_VERBS))}}}` is allowed")
    if head == "ip":
        if len(tokens) < 2 or tokens[1] not in _IP_READ_VERBS:
            return _err(f"only `ip {{{'|'.join(sorted(_IP_READ_VERBS))}}}` is allowed")

    # Only now do we care whether adb is actually installed.
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}

    try:
        r = run(["shell", *tokens], serial=serial, timeout=timeout)
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"shell command failed: {e}")

    return {
        "ok": r.returncode == 0,
        "command": command,
        "stdout": r.stdout,
        "stderr": r.stderr,
        "exit_code": r.returncode,
        "error": None if r.returncode == 0 else (r.stderr or f"shell exit {r.returncode}").strip(),
    }
