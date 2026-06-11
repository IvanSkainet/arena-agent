"""Sandboxed command execution runtime helpers."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Callable

SANDBOX_CONFIG: dict[str, Any] = {
    "enabled": True,
    "max_cpu_seconds": 30,
    "max_memory_mb": 256,
    "max_output_bytes": 100 * 1024,
    "allowed_commands": ["python3", "python", "bash", "sh", "node", "echo", "cat", "ls", "grep", "head", "tail", "wc", "sort", "uniq", "cut", "tr", "date", "whoami", "id", "env", "printenv", "which", "pwd"],
    "blocked_env_vars": ["ARENA_TOKEN", "TOKEN", "SECRET", "PASSWORD", "KEY"],
}


async def run_sandboxed(
    cmd: str,
    timeout: int = 30,
    memory_mb: int = 256,
    *,
    root_agent: Path,
    decode_output_fn: Callable[[bytes], str],
) -> dict[str, Any]:
    """Run a command in a sandboxed environment with resource limits.

    Uses subprocess with restricted environment, timeout, and output limits.
    On Windows, uses the existing AppContainer runner when available.
    """
    result: dict[str, Any] = {"ok": False, "timed_out": False, "memory_exceeded": False}

    # Sanitize environment.
    clean_env = dict(os.environ)
    for key in list(clean_env.keys()):
        for blocked in SANDBOX_CONFIG["blocked_env_vars"]:
            if blocked in key.upper():
                clean_env.pop(key, None)

    # Add sandbox indicator.
    clean_env["ARENA_SANDBOX"] = "1"

    if sys.platform == "win32":
        ac_runner = Path(root_agent) / "scripts" / "appcontainer_run.ps1"
        if ac_runner.exists():
            cmd = f'powershell -NoProfile -ExecutionPolicy Bypass -File "{ac_runner}" "{cmd}"'

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=clean_env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=min(timeout, SANDBOX_CONFIG["max_cpu_seconds"]),
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            result["timed_out"] = True
            result["error"] = f"timeout after {timeout}s"
            return result

        out = decode_output_fn(stdout)
        err = decode_output_fn(stderr)
        max_out = SANDBOX_CONFIG["max_output_bytes"]

        if len(out) > max_out:
            out = out[:max_out] + f"\n...[truncated, {len(out) - max_out} bytes omitted]"
        if len(err) > max_out // 2:
            err = err[:max_out // 2] + "\n...[truncated]"

        result["ok"] = proc.returncode == 0
        result["exit_code"] = proc.returncode
        result["stdout"] = out
        result["stderr"] = err

    except Exception as e:
        result["error"] = str(e)

    return result
