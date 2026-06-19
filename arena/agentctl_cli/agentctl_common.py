"""Shared helpers for the agentctl CLI."""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

from arena.constants import VERSION
ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
BRIDGE_URL = os.environ.get("ARENA_BRIDGE_URL", "http://127.0.0.1:8765")
BIN = ROOT / "bin"
SCRIPTS = ROOT / "scripts"


def _load_token() -> str:
    for token_path in (Path(os.environ.get("ARENA_TOKEN_FILE", "")) if os.environ.get("ARENA_TOKEN_FILE") else None,
                       ROOT / "token.txt",
                       Path.home() / "arena-bridge" / "token.txt"):
        if token_path and token_path.exists():
            return token_path.read_text(encoding="utf-8", errors="replace").strip().split("\n")[0].strip()
    return os.environ.get("ARENA_BRIDGE_TOKEN", "")


BRIDGE_TOKEN = _load_token()


def _ssl_context(url: str):
    ctx = ssl.create_default_context() if url.startswith("https") else None
    if ctx:
        ctx.check_hostname = False
        ctx.verify_mode = 0
    return ctx


def bridge_get(path: str, token: bool = True, timeout: int = 15) -> Any:
    url = f"{BRIDGE_URL}{path}"
    req = urllib.request.Request(url)
    if token and BRIDGE_TOKEN:
        req.add_header("Authorization", f"Bearer {BRIDGE_TOKEN}")
    ctx = _ssl_context(url)
    kwargs: dict[str, Any] = {"timeout": timeout}
    if ctx:
        kwargs["context"] = ctx
    with urllib.request.urlopen(req, **kwargs) as resp:
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
    with urllib.request.urlopen(req, **kwargs) as resp:
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
