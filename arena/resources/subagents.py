"""Subagent runtime helpers."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


def spawn_subagent(data: dict[str, Any], *, bin_dir: Path, subprocess_kwargs_fn: Callable[[], dict]) -> dict[str, Any]:
    cmd = data.get("cmd", "")
    name = data.get("name", "")
    wait = data.get("wait", True)
    timeout = data.get("timeout", 300)

    cmd_args = [sys.executable, str(bin_dir / "subagent.py"), "spawn", cmd]
    if name:
        cmd_args += ["--name", name]
    if wait:
        cmd_args += ["--wait"]
    cmd_args += ["--timeout", str(timeout)]

    try:
        proc = subprocess.run(cmd_args, capture_output=True, text=True, timeout=timeout + 30, **subprocess_kwargs_fn())
        return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "stdout": proc.stdout[-10000:], "stderr": proc.stderr[-3000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "exit_code": -2, "stdout": "", "stderr": str(e)}
