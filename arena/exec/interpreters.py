"""Interpreter table + shell-safe path quoting for /v1/exec/script.

Split out of `handlers.py` in v4.163.0: that module crossed the 600-line
runtime cap while bug #52 was being fixed, and this is the natural seam --
nothing here touches aiohttp, auth or the request lifecycle.

The one rule this file exists to enforce: the templates below are handed
to a **shell**, so the script path must be quoted before substitution.
Interpolating it bare made the whole endpoint unusable on any root
containing a space.
"""
from __future__ import annotations

import os
import shlex
import shutil

# v4.2.0: interpreter → (cmdline template, filename suffix, unix?)
# The template takes ``{path}`` for the temp script path; the shell
# quoting is single-arg because we execute via create_subprocess_exec-
# equivalent through the existing run_shell_command shim, which uses
# shell mode. Interpreters that need special flags (bash -euo pipefail)
# are configured here so agents don't have to think about it.
_INTERPRETERS: dict[str, dict[str, object]] = {
    "bash":       {"cmd": "bash -euo pipefail {path}",        "suffix": ".sh",   "unix": True},
    "sh":         {"cmd": "sh -eu {path}",                     "suffix": ".sh",   "unix": True},
    "python":     {"cmd": "python3 {path}",                    "suffix": ".py",   "unix": True},
    "python3":    {"cmd": "python3 {path}",                    "suffix": ".py",   "unix": True},
    "node":       {"cmd": "node {path}",                       "suffix": ".js",   "unix": True},
    "pwsh":       {"cmd": "pwsh -NoProfile -File {path}",      "suffix": ".ps1",  "unix": False},
    "powershell": {"cmd": "powershell -NoProfile -File {path}","suffix": ".ps1",  "unix": False},
}

_DEFAULT_INTERPRETER_UNIX = "bash"
_DEFAULT_INTERPRETER_WIN = "powershell"



def _quote_path(path: str) -> str:
    """Quote a filesystem path for the shell that will run the command.

    `shlex.quote` is POSIX-only: it wraps in single quotes, which cmd.exe
    and PowerShell do not treat as quoting at all -- `'C:\\Program Files'`
    would arrive with the quote characters intact. Windows therefore gets
    double quotes instead.

    A path cannot contain a double quote on Windows (the filesystem
    forbids it), so there is nothing to escape on that branch; on POSIX
    shlex handles every case including embedded quotes.
    """
    if os.name == "nt":
        return f'"{path}"'
    return shlex.quote(path)

def _resolve_interpreter(name: str) -> tuple[str, dict[str, object]] | None:
    """Return (name, config) for a supported interpreter or None.
    Falls back to platform default when name is empty."""
    if not name:
        name = _DEFAULT_INTERPRETER_WIN if os.name == "nt" else _DEFAULT_INTERPRETER_UNIX
    lower = name.strip().lower()
    if lower in _INTERPRETERS:
        return lower, _INTERPRETERS[lower]
    return None

def _which_interpreter(cmdline_template: str) -> str | None:
    """Return the resolved absolute path of the interpreter binary,
    or None if it's not on PATH. Used so a 404-style 'bash not
    installed' comes back as a clear 400, not a shell error."""
    first = cmdline_template.split()[0]
    return shutil.which(first)
