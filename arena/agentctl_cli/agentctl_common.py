"""Shared helpers for the agentctl CLI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

from arena.constants import VERSION
from arena.agentctl_cli.tls import build_ssl_context
ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
BRIDGE_URL = os.environ.get("ARENA_BRIDGE_URL", "http://127.0.0.1:8765")
BIN = ROOT / "bin"
SCRIPTS = ROOT / "scripts"


def _load_token() -> str:
    """Resolve the bearer token from (in priority order):

    1. ``ARENA_TOKEN_FILE`` env var pointing at a file (highest
       priority — used by tests and by operators who keep the
       token in a password manager mount).
    2. ``ARENA_BRIDGE_TOKEN`` env var directly. **v4.41.0
       change**: this used to be the lowest-priority source,
       which meant a stale ``token.txt`` in the user's home
       silently overrode a freshly-exported env var. That was
       an unpleasant surprise — everything from tests to
       ``ARENA_BRIDGE_TOKEN=$(cat other-token)`` broke without
       any diagnostic. Env now wins over disk. Disk still wins
       over the env-empty case so out-of-the-box behaviour
       (``token.txt`` present, no env set) is unchanged.
    3. ``$ARENA_AGENT_HOME/token.txt`` (defaults to
       ``~/arena-bridge/token.txt``).
    4. Fixed ``~/arena-bridge/token.txt`` fallback for the case
       where ``ARENA_AGENT_HOME`` points somewhere else but the
       standard install location still has a token.

    An empty file counts as "not present" — we don't want to
    return an empty string from a corrupted install and then
    have every request fail 401.
    """
    # 1. Explicit file wins over everything.
    explicit = os.environ.get("ARENA_TOKEN_FILE", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            tok = _read_first_line(p)
            if tok:
                return tok
    # 2. Env variable next -- v4.41.0 promoted this above disk
    # so an operator can override a stale ``token.txt`` without
    # editing files.
    env_tok = os.environ.get("ARENA_BRIDGE_TOKEN", "").strip()
    if env_tok:
        return env_tok
    # 3. Disk fallback, standard locations.
    for token_path in (ROOT / "token.txt",
                       Path.home() / "arena-bridge" / "token.txt"):
        if token_path.exists():
            tok = _read_first_line(token_path)
            if tok:
                return tok
    return ""


def _read_first_line(path: Path) -> str:
    """Read a token file's first non-empty line. Extracted so
    _load_token stays readable and every disk-read applies the
    same stripping rules."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in raw.splitlines():
        s = line.strip()
        if s:
            return s
    return ""


BRIDGE_TOKEN = _load_token()


def _ssl_context(url: str):
    """Backward-compat wrapper -- v4.41.0 delegates every SSL
    context construction to ``arena/agentctl_cli/tls.py`` so
    verify-by-default and the ARENA_INSECURE_TLS opt-out live
    in exactly one place. Kept as a private name so any legacy
    caller still importing ``_ssl_context`` from this module
    keeps working."""
    return build_ssl_context(url)


def bridge_get(path: str, token: bool = True, timeout: int = 15) -> Any:
    url = f"{BRIDGE_URL}{path}"
    req = urllib.request.Request(url)
    if token and BRIDGE_TOKEN:
        req.add_header("Authorization", f"Bearer {BRIDGE_TOKEN}")
    ctx = _ssl_context(url)
    kwargs: dict[str, Any] = {"timeout": timeout}
    if ctx:
        kwargs["context"] = ctx
    with urllib.request.urlopen(req, **kwargs) as resp:  # nosec B310 -- operator-configured BRIDGE_URL; TLS-verified per arena/agentctl_cli/tls.py
        return json.loads(resp.read().decode())


def bridge_post(path: str, data: dict, token: bool = True, timeout: int = 20) -> Any:
    url = f"{BRIDGE_URL}{path}"
    req = urllib.request.Request(url, data=json.dumps(data).encode(), method="POST")
    if token and BRIDGE_TOKEN:
        req.add_header("Authorization", f"Bearer {BRIDGE_TOKEN}")
    req.add_header("Content-Type", "application/json")
    ctx = _ssl_context(url)
    kwargs: dict[str, Any] = {"timeout": timeout}
    if ctx:
        kwargs["context"] = ctx
    with urllib.request.urlopen(req, **kwargs) as resp:  # nosec B310 -- operator-configured BRIDGE_URL; TLS-verified per arena/agentctl_cli/tls.py
        return json.loads(resp.read().decode())


def exec_bridge(cmd: str, timeout: int = 30) -> dict:
    return bridge_post("/v1/exec", {"cmd": cmd, "timeout": timeout})


def run_script(script: str, args: list[str] | None = None) -> None:
    py = sys.executable or "python3"
    try:
        subprocess.run([py, str(SCRIPTS / script)] + (args or []), check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)


def run_bin(tool: str, args: list[str] | None = None) -> None:
    py = sys.executable or "python3"
    tool_path = BIN / tool
    cmd = [py, str(tool_path)] if tool_path.suffix == ".py" else [str(tool_path)]
    try:
        subprocess.run(cmd + (args or []), check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
