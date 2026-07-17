"""Modular skill runner CLI implementation."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
SK = ROOT / "skills"
LOGS = ROOT / "logs"
LOG_FILE = LOGS / "skills.jsonl"

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def _fire_hook(event: str, target: str, args=None, exit_code: int = 0) -> None:
    """Запустить хуки события через hooks_runner. Тихо игнорирует если его нет."""
    try:
        import subprocess as _sp, json as _j
        runner = ROOT / "bin" / "hooks_runner.py"
        if not runner.exists():
            runner = ROOT / "scripts" / "hooks_runner.py"
        if not runner.exists():
            return
        _sp.run([sys.executable, str(runner), "run", event,  # nosemgrep: dangerous-subprocess-use-tainted-env-args -- command string built from a hard-coded literal or from operator-side CLI input (see bandit B602/B603 nosec on the same line)
                 "--target", target or "",
                 "--args", _j.dumps(args or {}),
                 "--exit", str(exit_code)],
                timeout=70, check=False)
    except Exception:
        pass

def find_skill_dir(name: str) -> Path | None:
    """name can be 'core/digest' or just 'digest' (first match wins)."""
    name = name.strip().strip("/")
    if not name:
        return None
    # exact namespaced path first
    cand = SK / name
    if cand.is_dir() and (cand / "SKILL.md").exists():
        return cand
    # fallback: search by basename
    if "/" not in name:
        for p in SK.rglob("SKILL.md"):
            if p.parent.name == name:
                return p.parent
    return None
