"""Runner for `scripts/inventory.py`.

This module owns the subprocess/path mechanics for collecting the full system
inventory. API handlers remain free to choose executors/timeouts, while this
runner stays stdlib-only and testable.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


def find_inventory_script(bridge_dir: Path, root_agent: Path | None = None) -> Path | None:
    candidates = [bridge_dir / "scripts" / "inventory.py"]
    if root_agent is not None:
        candidates.append(root_agent / "scripts" / "inventory.py")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def run_inventory(
    *,
    bridge_dir: Path,
    root_agent: Path | None = None,
    section: str | None = None,
    fmt: str = "text",
    timeout: int = 30,
    python_executable: str | None = None,
) -> dict[str, Any]:
    """Run inventory.py and return text or parsed JSON result."""
    script = find_inventory_script(bridge_dir, root_agent)
    if not script:
        return {"ok": False, "error": "inventory.py not found in any known location"}

    args = [python_executable or sys.executable or "python3", str(script)]
    if fmt == "json":
        args.append("--json")
    if section:
        args.extend(["--section", section])

    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "timeout": timeout,
            "encoding": "utf-8",
            "errors": "replace",
            "env": env,
        }
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        proc = subprocess.run(args, **kwargs)
        if fmt == "json":
            try:
                parsed = json.loads(proc.stdout)
                return {
                    "ok": proc.returncode == 0,
                    "inventory": parsed,
                    "exit_code": proc.returncode,
                    "stderr": proc.stderr[-2000:],
                }
            except Exception as e:
                return {
                    "ok": False,
                    "error": f"JSON parse failed: {e}",
                    "stdout": proc.stdout[-2000:],
                    "stderr": proc.stderr[-2000:],
                }
        return {
            "ok": proc.returncode == 0,
            "text": proc.stdout,
            "exit_code": proc.returncode,
            "stderr": proc.stderr[-2000:],
            "script": str(script),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"inventory.py timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
