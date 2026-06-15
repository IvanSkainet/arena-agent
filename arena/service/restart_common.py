"""Common helpers for detached bridge restart/respawn."""
from __future__ import annotations

import os
import platform
import subprocess as sp
import tempfile
from dataclasses import dataclass
from pathlib import Path

from arena.constants import BRIDGE_DIR, TOKEN_FILE


@dataclass(frozen=True)
class RestartContext:
    port: int
    sys_name: str
    bridge_py: str
    token_file: str
    task_name: str
    pid: int


def build_restart_context(port: int) -> RestartContext:
    return RestartContext(
        port=port,
        sys_name=platform.system(),
        bridge_py=str(BRIDGE_DIR / "unified_bridge.py"),
        token_file=str(TOKEN_FILE),
        task_name=os.environ.get("ARENA_TASK_NAME", "ArenaUnifiedBridge"),
        pid=os.getpid(),
    )


def temp_script_path(prefix: str, suffix: str, pid: int) -> Path:
    return Path(tempfile.gettempdir()) / f"{prefix}_{pid}{suffix}"


def write_script(path: Path, content: str, *, encoding: str = "utf-8", executable: bool = False) -> None:
    path.write_text(content, encoding=encoding, newline="")
    if executable:
        path.chmod(0o755)


def launch_detached_shell_script(path: Path) -> None:
    sp.Popen(
        ["bash", str(path)],
        start_new_session=True,
        stdin=sp.DEVNULL,
        stdout=sp.DEVNULL,
        stderr=sp.DEVNULL,
        close_fds=True,
    )


def render_template(template: str, ctx: RestartContext) -> str:
    return (
        template
        .replace("__TASK__", ctx.task_name)
        .replace("__PID__", str(ctx.pid))
        .replace("__PORT__", str(ctx.port))
        .replace("__BRIDGE__", ctx.bridge_py)
        .replace("__TOKEN_FILE__", ctx.token_file)
    )
